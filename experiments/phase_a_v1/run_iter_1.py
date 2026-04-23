"""Phase A iteration 1: prompt Kimi 2.6-1 for a Cedar-micro generator.

Pipeline:
  1. Read the prompt from prompts/kimi_v1_initial.md
  2. Call the Kimi 2.6-1 Azure endpoint directly (openai-compat API)
  3. Save the raw response to outputs/iter_1_kimi_raw.lean
  4. Also save the full request+response record to traces/iter_1_kimi.json
  5. Compile the output inside the monolith container as CedarMicro/GenLLM.lean
  6. If compile succeeds, run a sample driver; if not, capture errors

Uses direct Azure OpenAI-compatible calls (not litellm) to stay
transparent on what exactly was sent and received.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PROMPT_PATH = HERE / "prompts" / "kimi_v1_initial.md"
RAW_OUT = HERE / "outputs" / "iter_1_kimi_raw.lean"
TRACE_OUT = HERE / "traces" / "iter_1_kimi.json"
GEN_LLM_DST = REPO_ROOT / "cedar-micro" / "CedarMicro" / "GenLLM.lean"

KIMI_MODEL = os.environ.get("KIMI_K26_MODEL", "kimi-k2.6-1")
KIMI_KEY = os.environ.get("KIMI_K26_API_KEY")
KIMI_BASE = os.environ.get("KIMI_K26_API_BASE")

IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


def call_kimi(prompt_text: str) -> tuple[str, dict]:
    if not (KIMI_KEY and KIMI_BASE):
        raise RuntimeError("KIMI_K26_API_KEY / KIMI_K26_API_BASE unset")
    url = f"{KIMI_BASE}/chat/completions?api-version=2024-05-01-preview"
    body = {
        "model": KIMI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Lean 4 expert specialising in property-based "
                    "testing generators. Output only compilable Lean 4 source. "
                    "No prose, no markdown fences."
                ),
            },
            {"role": "user", "content": prompt_text},
        ],
        # Kimi 2.6 is a reasoning model. Most of the budget goes into
        # the reasoning trace before any visible output. 32k leaves
        # enough headroom for the reasoning + a few hundred lines of
        # Lean source.
        "max_tokens": 32000,
        "temperature": 0.2,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"api-key": KIMI_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.monotonic() - t

    msg = payload["choices"][0]["message"]
    text = msg.get("content")
    finish = payload["choices"][0].get("finish_reason")
    if not text:
        # Kimi 2.6 reasoning models: if the model ran out of token
        # budget partway through reasoning, content is null. Surface
        # the reasoning for debug, fail loudly.
        reasoning = msg.get("reasoning_content", "") or ""
        raise RuntimeError(
            f"Kimi returned empty content (finish_reason={finish}). "
            f"Reasoning length: {len(reasoning)} chars. "
            f"First 200 chars of reasoning: {reasoning[:200]!r}"
        )
    usage = payload.get("usage", {})
    record = {
        "finish_reason": finish,
        "model": KIMI_MODEL,
        "prompt_path": str(PROMPT_PATH.relative_to(REPO_ROOT)),
        "elapsed_sec": round(elapsed, 2),
        "tokens": usage,
        "response_length_chars": len(text),
    }
    return text, record


def strip_code_fences(text: str) -> str:
    """Some models still wrap Lean in ``` fences despite the instruction."""
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines).strip()


def compile_in_image(source: str) -> tuple[bool, str]:
    """Write the source to CedarMicro/GenLLM.lean, patch CedarMicro.lean to
    import it, and lake build inside the image."""
    GEN_LLM_DST.write_text(source + "\n")
    # Patch CedarMicro.lean to import GenLLM (idempotent).
    toplevel = REPO_ROOT / "cedar-micro" / "CedarMicro.lean"
    text = toplevel.read_text()
    if "import CedarMicro.GenLLM" not in text:
        toplevel.write_text(text.rstrip() + "\nimport CedarMicro.GenLLM\n")
    proc = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{REPO_ROOT}:/work",
            "-w", "/work/cedar-micro",
            IMAGE,
            "bash", "-c",
            "elan default leanprover/lean4:v4.24.0 >/dev/null 2>&1 && "
            "lake build CedarMicro.GenLLM 2>&1 | tail -50",
        ],
        capture_output=True, text=True, timeout=600,
    )
    out = proc.stdout + "\n" + proc.stderr
    ok = proc.returncode == 0 and "Build completed" in out
    return ok, out


def main() -> int:
    prompt = PROMPT_PATH.read_text()
    print(f"[phase A iter 1] calling {KIMI_MODEL} at {KIMI_BASE}")
    try:
        text, record = call_kimi(prompt)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body[:500]}")
        return 1
    except Exception as e:
        print(f"Kimi call failed: {type(e).__name__}: {e}")
        return 1

    clean = strip_code_fences(text)
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(clean)
    TRACE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TRACE_OUT.write_text(json.dumps({**record, "raw_output_head": clean[:400]},
                                    indent=2, sort_keys=True))
    print(f"[phase A iter 1] wrote {RAW_OUT} ({len(clean)} chars), "
          f"{record['tokens']}, {record['elapsed_sec']}s")

    print("[phase A iter 1] attempting lake build inside kairos-cedar image ...")
    ok, log = compile_in_image(clean)
    log_path = HERE / "outputs" / "iter_1_compile.log"
    log_path.write_text(log)
    if ok:
        print(f"[phase A iter 1] COMPILE PASS. log at {log_path}")
        print("[phase A iter 1] next: sample + verify (iter_1_sample.py)")
        return 0
    else:
        print(f"[phase A iter 1] COMPILE FAIL. log at {log_path}")
        print("[phase A iter 1] tail of build log:")
        for line in log.splitlines()[-20:]:
            print("    " + line)
        return 1


if __name__ == "__main__":
    sys.exit(main())
