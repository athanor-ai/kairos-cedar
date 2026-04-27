#!/usr/bin/env bash
# Build and run byte_fuzz_baseline in `bytes` mode for 1000 attempts.
# Prints parser-reach + evaluator-reach summary.

set -euo pipefail

cd "$(dirname "$0")/../../experiments/byte_fuzz_baseline"

echo "Building byte_fuzz_baseline (release) ..."
cargo build --release

echo
echo "Running bytes mode, n=1000, seed=42 ..."
./target/release/byte_fuzz_baseline --mode bytes --n 1000 --seed 42 \
  | tail -1
