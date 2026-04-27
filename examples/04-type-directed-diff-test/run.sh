#!/usr/bin/env bash
# Run the §8 type-directed differential pipeline at N=20.
# License-free local mode (--no-session): no Tahoe trace, no DB writes,
# nothing leaves the box.

set -euo pipefail

cd "$(dirname "$0")/../.."

python3 experiments/phase_c_diff/run_diff.py --n 20 --no-session
