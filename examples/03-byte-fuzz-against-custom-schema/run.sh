#!/usr/bin/env bash
# Build and run byte_fuzz_baseline in `bytes` mode for 1000 attempts.
# Prints parser-reach + evaluator-reach summary.

set -euo pipefail

cd "$(dirname "$0")/../../experiments/byte_fuzz_baseline"

echo "Building byte_fuzz_baseline (release, nightly) ..."
# cedar-policy 4.10's transitive deps require Rust nightly (edition2024).
# The container has the nightly toolchain installed at $RUST_NIGHTLY.
cargo +"${RUST_NIGHTLY:-nightly}" build --release

echo
echo "Running bytes mode, n=1000, seed=42 ..."
./target/release/byte_fuzz_baseline --mode bytes --n 1000 --seed 42 \
  | tail -1
