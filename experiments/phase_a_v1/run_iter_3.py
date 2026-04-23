"""Phase A iteration 3: more specific feedback. Iter 2 tried termination_by
but could not close the numeric goal. Iter 3 suggests the simpler
structural fix: recurse on the list tail (definitionally smaller)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PREV_SRC = HERE / "outputs" / "iter_2_kimi_raw.lean"
PREV_LOG = HERE / "outputs" / "iter_2_compile.log"
OUT = HERE / "outputs" / "iter_3_kimi_raw.lean"
TRACE = HERE / "traces" / "iter_3_kimi.json"
GEN_LLM_DST = REPO_ROOT / "cedar-micro" / "CedarMicro" / "GenLLM.lean"
IMAGE = "ghcr.io/athanor-ai/kairos-cedar:latest"


def call_kimi(messages):
    url = f"{os.environ['KIMI_K26_API_BASE']}/chat/completions?api-version=2024-05-01-preview"
    body = {"model": os.environ.get("KIMI_K26_MODEL", "kimi-k2.6-1"),
            "messages": messages, "max_tokens": 32000, "temperature": 0.1}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"api-key": os.environ["KIMI_K26_API_KEY"], "Content-Type": "application/json"},
        method="POST")
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode())
    msg = payload["choices"][0]["message"]
    text = msg.get("content")
    if not text:
        raise RuntimeError("Kimi empty content")
    return text, payload.get("usage", {}), time.monotonic() - t


def strip_fences(text):
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines).strip()


def compile_in_image(source):
    GEN_LLM_DST.write_text(source + "\n")
    proc = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{REPO_ROOT}:/work",
         "-w", "/work/cedar-micro", IMAGE, "bash", "-c",
         "elan default leanprover/lean4:v4.24.0 >/dev/null 2>&1 && "
         "lake build CedarMicro.GenLLM 2>&1 | tail -50"],
        capture_output=True, text=True, timeout=600)
    return proc.returncode == 0 and "Build completed" in proc.stdout, proc.stdout + "\n" + proc.stderr


def main():
    prev_src = PREV_SRC.read_text()
    err_tail = "\n".join(PREV_LOG.read_text().splitlines()[-25:])

    prompt = f"""Your previous attempt added `termination_by` but Lean still cannot close the numeric goal (something about `xs.length / 2` vs `(x :: y :: ys).length`). The root cause is that `List.take n xs` and `List.drop n xs` are not definitionally smaller than `xs` in Lean's structural recursion checker, even with explicit well-founded metrics.

**Concrete fix**: rewrite `pickFromList` to recurse structurally on the list tail. Each recursive call passes `xs.tail!` (or the tail from a `x :: rest` pattern match), which IS definitionally smaller, so Lean accepts the recursion automatically with no `termination_by`.

Replacement pattern:

```lean
def pickFromList (default : α) (xs : List α) : Gen α :=
  match xs with
  | []        => Gen.pure default
  | [x]       => Gen.pure x
  | x :: rest => Gen.pick (Gen.pure x) (pickFromList default rest)
```

This recurses on `rest`, which is structurally smaller, so no termination_by is needed. Every list element gets a roughly equal chance of being picked (the first element wins with probability 1/2, the second with 1/4, etc.).

Apply that exact `pickFromList` rewrite. Keep everything else identical to iter 2. Return only the corrected Lean source, no prose, no fences.

Previous source:
```lean
{prev_src}
```

Compile error tail:
```
{err_tail}
```"""

    text, usage, elapsed = call_kimi([
        {"role": "system", "content": "You are a Lean 4 expert. Output only compilable Lean source, no prose."},
        {"role": "user", "content": prompt},
    ])
    clean = strip_fences(text)
    OUT.write_text(clean)
    TRACE.write_text(json.dumps({"usage": usage, "elapsed_sec": round(elapsed, 2),
                                  "output_head": clean[:300]}, indent=2))
    print(f"[iter 3] wrote {OUT} ({len(clean)} chars), tokens={usage}, {elapsed:.1f}s")

    ok, log = compile_in_image(clean)
    (HERE / "outputs" / "iter_3_compile.log").write_text(log)
    if ok:
        print("[iter 3] COMPILE PASS")
        return 0
    print("[iter 3] COMPILE FAIL, tail:")
    for line in log.splitlines()[-15:]:
        print("    " + line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
