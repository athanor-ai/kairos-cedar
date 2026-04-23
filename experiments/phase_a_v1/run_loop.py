"""Phase A verification-feedback loop.

One generic script that implements the paper's core methodology:
prompt an LLM for a generator, compile in the monolith image, feed
any compile error back, repeat until the output compiles cleanly.

Once compilation converges, the next stage (`run_sample_verify.py`)
samples from the generator and checks each output against the Lean
predicate.

Usage:
    python3 experiments/phase_a_v1/run_loop.py
    MAX_ITERS=8 python3 experiments/phase_a_v1/run_loop.py
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
INITIAL_PROMPT = HERE / "prompts" / "kimi_v1_initial.md"
GEN_LLM_DST = REPO_ROOT / "cedar-micro" / "CedarMicro" / "GenLLM.lean"
OUT_DIR = HERE / "outputs"
TRACE_DIR = HERE / "traces"
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")
MAX_ITERS = int(os.environ.get("MAX_ITERS", "6"))


def call_kimi(messages: list[dict]) -> tuple[str, dict, float]:
    url = f"{os.environ['KIMI_K26_API_BASE']}/chat/completions?api-version=2024-05-01-preview"
    body = {
        "model": os.environ.get("KIMI_K26_MODEL", "kimi-k2.6-1"),
        "messages": messages,
        "max_tokens": 32000,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"api-key": os.environ["KIMI_K26_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode())
    msg = payload["choices"][0]["message"]
    text = msg.get("content")
    if not text:
        raise RuntimeError(
            f"Kimi empty content (finish={payload['choices'][0].get('finish_reason')}, "
            f"reasoning_tokens={payload.get('usage', {}).get('reasoning_tokens', '?')})"
        )
    return text, payload.get("usage", {}), time.monotonic() - t


def strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines).strip()


def compile_source(source: str) -> tuple[bool, str]:
    GEN_LLM_DST.write_text(source + "\n")
    proc = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{REPO_ROOT}:/work",
            "-w", "/work/cedar-micro",
            IMAGE,
            "bash", "-c",
            "elan default leanprover/lean4:v4.24.0 >/dev/null 2>&1 && "
            "lake build CedarMicro.GenLLM 2>&1 | tail -60",
        ],
        capture_output=True, text=True, timeout=600,
    )
    log = proc.stdout + "\n" + proc.stderr
    return proc.returncode == 0 and "Build completed" in log, log


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a Lean 4 expert specialising in property-based testing. "
                "Output only compilable Lean source. No prose, no fences."
            ),
        },
        {"role": "user", "content": INITIAL_PROMPT.read_text()},
    ]

    history: list[dict] = []

    for it in range(1, MAX_ITERS + 1):
        print(f"\n[loop] iteration {it}/{MAX_ITERS}")
        try:
            text, usage, elapsed = call_kimi(messages)
        except Exception as e:
            print(f"[loop] Kimi call failed: {type(e).__name__}: {e}")
            return 1
        source = strip_fences(text)
        src_path = OUT_DIR / f"loop_iter_{it}.lean"
        src_path.write_text(source)
        print(f"[loop]   wrote {src_path.name} ({len(source)} chars, "
              f"{usage.get('reasoning_tokens', 0)}/{usage.get('completion_tokens', 0)} "
              f"reasoning/total, {elapsed:.1f}s)")

        ok, log = compile_source(source)
        log_path = OUT_DIR / f"loop_iter_{it}_compile.log"
        log_path.write_text(log)

        history.append({
            "iteration": it,
            "source_chars": len(source),
            "reasoning_tokens": usage.get("reasoning_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "call_elapsed_sec": round(elapsed, 2),
            "compile_ok": ok,
        })

        if ok:
            print(f"[loop]   COMPILE PASS. converged at iteration {it}")
            break
        else:
            err_tail = "\n".join(log.splitlines()[-30:])
            print(f"[loop]   COMPILE FAIL, tail:")
            for line in log.splitlines()[-10:]:
                print(f"    {line}")
            # Append the attempt + the error to the conversation.
            messages.append({"role": "assistant", "content": source})
            messages.append({
                "role": "user",
                "content": (
                    "That source did not compile in the kairos-cedar image. "
                    "Lean 4.24 produced the following errors. Correct the source "
                    "to compile cleanly and return only the Lean source (no prose, "
                    "no fences). Preserve the public API `genWellTyped : List Ty -> Ty -> Gen Expr`.\n\n"
                    f"```\n{err_tail}\n```"
                ),
            })
    else:
        print(f"[loop] max iterations ({MAX_ITERS}) reached without converging")

    trace_file = TRACE_DIR / "loop_summary.json"
    total_reasoning = sum(h["reasoning_tokens"] for h in history)
    total_completion = sum(h["completion_tokens"] for h in history)
    total_prompt = sum(h["prompt_tokens"] for h in history)
    # Kimi 2.6 pricing is not stable; use 5 USD / 1M in+out as a placeholder.
    usd_estimate = (total_prompt + total_completion) * 5.0 / 1_000_000
    summary = {
        "model": os.environ.get("KIMI_K26_MODEL", "kimi-k2.6-1"),
        "max_iters": MAX_ITERS,
        "iterations": history,
        "converged": any(h["compile_ok"] for h in history),
        "iterations_to_converge": next(
            (h["iteration"] for h in history if h["compile_ok"]), None
        ),
        "total_reasoning_tokens": total_reasoning,
        "total_completion_tokens": total_completion,
        "total_prompt_tokens": total_prompt,
        "usd_estimate_5usd_per_million": round(usd_estimate, 4),
    }
    trace_file.write_text(json.dumps(summary, indent=2))
    print(f"\n[loop] summary written to {trace_file}")
    print(f"  converged: {summary['converged']} at iter {summary['iterations_to_converge']}")
    print(f"  total tokens: {total_prompt + total_completion} ({total_reasoning} reasoning)")
    print(f"  cost estimate: ~${usd_estimate:.3f}")

    return 0 if summary["converged"] else 1


if __name__ == "__main__":
    sys.exit(main())
