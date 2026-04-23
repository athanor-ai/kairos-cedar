"""Phase A iteration 2: feed the iter_1 compile error back to Kimi 2.6-1.

Demonstrates the verification-feedback loop: Lean predicates/compiler
reject the model's generator; we feed the exact rejection reason back;
model iterates.
"""

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
PREV_SRC = HERE / "outputs" / "iter_1_kimi_raw.lean"
PREV_LOG = HERE / "outputs" / "iter_1_compile.log"
OUT = HERE / "outputs" / "iter_2_kimi_raw.lean"
TRACE = HERE / "traces" / "iter_2_kimi.json"
GEN_LLM_DST = REPO_ROOT / "cedar-micro" / "CedarMicro" / "GenLLM.lean"
IMAGE = "ghcr.io/athanor-ai/kairos-cedar:latest"


def call_kimi(messages):
    url = f"{os.environ['KIMI_K26_API_BASE']}/chat/completions?api-version=2024-05-01-preview"
    body = {
        "model": os.environ.get("KIMI_K26_MODEL", "kimi-k2.6-1"),
        "messages": messages,
        "max_tokens": 32000,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"api-key": os.environ["KIMI_K26_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    msg = payload["choices"][0]["message"]
    text = msg.get("content")
    if not text:
        reasoning = msg.get("reasoning_content", "")
        raise RuntimeError(
            f"Kimi empty content (finish={payload['choices'][0].get('finish_reason')}); "
            f"reasoning_len={len(reasoning)}"
        )
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
        capture_output=True, text=True, timeout=600,
    )
    return proc.returncode == 0 and "Build completed" in proc.stdout, proc.stdout + "\n" + proc.stderr


def main():
    prev_src = PREV_SRC.read_text()
    prev_log = PREV_LOG.read_text()
    # Trim the compile log to the actual error block.
    err_tail = "\n".join(prev_log.splitlines()[-35:])

    feedback_prompt = f"""Your previous Lean 4 source compiled partially but failed the termination checker on `pickFromList`. Lean needs a termination proof when `pickFromList` recurses into `List.take n xs` and `List.drop n xs`, because the compiler can't auto-derive that those are structurally smaller than `xs`.

The compile log (tail) is below. Produce a corrected Lean source that compiles cleanly. Keep the same structure and the same public API (`genWellTyped : List Ty -> Ty -> Gen Expr`). Add `termination_by` or refactor `pickFromList` so the recursion is structurally obvious. Do not use `partial`; the generator must be total.

Previous source:
```lean
{prev_src}
```

Compile log tail:
```
{err_tail}
```

Return only the corrected Lean source. No prose, no fences. Start with `import`."""

    text, usage, elapsed = call_kimi([
        {"role": "system", "content": "You are a Lean 4 expert specialising in property-based testing. Output only compilable Lean source. No prose, no fences."},
        {"role": "user", "content": feedback_prompt},
    ])
    clean = strip_fences(text)
    OUT.write_text(clean)
    TRACE.write_text(json.dumps({
        "usage": usage, "elapsed_sec": round(elapsed, 2),
        "output_head": clean[:300],
    }, indent=2))
    print(f"[iter 2] wrote {OUT} ({len(clean)} chars), tokens={usage}, {elapsed:.1f}s")

    ok, log = compile_in_image(clean)
    (HERE / "outputs" / "iter_2_compile.log").write_text(log)
    if ok:
        print("[iter 2] COMPILE PASS")
        return 0
    print("[iter 2] COMPILE FAIL, tail:")
    for line in log.splitlines()[-20:]:
        print("    " + line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
