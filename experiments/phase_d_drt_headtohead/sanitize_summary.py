"""Post-process summary.json to replace Python's `Infinity` with `null`.

Python's `json.dumps` on a `float('inf')` emits the literal `Infinity`,
which is invalid JSON and trips strict parsers. The current
`run_headtohead.py` returns `None` instead of `float('inf')` in
`make_comparison_row`, but if the summary was emitted by an older
version, this helper rewrites it in place.

Usage:
    python3 experiments/phase_d_drt_headtohead/sanitize_summary.py \
        experiments/phase_d_drt_headtohead/outputs/summary.json
"""
import json
import re
import sys
from pathlib import Path


def sanitize(path: Path) -> None:
    text = path.read_text()
    # Replace bare `Infinity` and `-Infinity` literals with `null`.
    sanitized = re.sub(r"(?<!\")\bInfinity\b(?!\")", "null", text)
    sanitized = re.sub(r"(?<!\")\b-Infinity\b(?!\")", "null", sanitized)
    sanitized = re.sub(r"(?<!\")\bNaN\b(?!\")", "null", sanitized)
    json.loads(sanitized)  # verify
    path.write_text(sanitized)
    print(f"sanitized {path}")


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <summary.json>", file=sys.stderr)
        return 2
    for arg in sys.argv[1:]:
        sanitize(Path(arg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
