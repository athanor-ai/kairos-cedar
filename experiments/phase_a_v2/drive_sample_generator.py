"""SDK-primitive smoke: drive kairos.lean.sample_generator against
cedar-micro's hand-authored genWellTyped. Confirms that the SDK's
new (ATH-546, PR #150) sample_generator helper closes the
Lake-project sampling loop end-to-end.

Not a paper table column — the hand-authored generator's numbers
are already in Table 1 col 1. This is pure SDK dogfood: exercise
the API on a known-good input and report shape + timing.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SDK_SRC = "/home/azureuser/agents/qa/athanor-sdk/src"
if SDK_SRC not in sys.path:
    sys.path.insert(0, SDK_SRC)

from kairos.lean import sample_generator  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CEDAR_MICRO = REPO_ROOT / "cedar-micro"


def main() -> int:
    t = time.monotonic()
    result = sample_generator(
        workspace=str(CEDAR_MICRO),
        module="CedarMicro.WellTyped",
        term_type="CedarMicro.Expr",
        generator_expr=(
            "sampleN 20 (CedarMicro.genWellTyped [.int, .bool, .int] .bool)"
        ),
        n=20,
        render_expr="(fun e => reprStr e)",
        extra_imports=["import Palamedes.Sample"],
        timeout_sec=300,
    )
    elapsed = time.monotonic() - t

    print(f"[sample_generator smoke] elapsed={elapsed:.2f}s")
    print(f"[sample_generator smoke] terms returned={len(result.terms)}")
    if result.terms:
        print("[sample_generator smoke] first 3 terms:")
        for t in result.terms[:3]:
            print(f"  {t[:120]}")
    if result.error:
        print(f"[sample_generator smoke] error: {result.error}")
    if result.stdout_tail:
        print(f"[sample_generator smoke] stdout tail:")
        print(result.stdout_tail[-800:])
    return 0 if result.terms else 1


if __name__ == "__main__":
    sys.exit(main())
