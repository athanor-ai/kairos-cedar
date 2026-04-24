#!/bin/bash
# Fleet sweep: sonnet + kimi + opus via EXP2_MODEL env var.
# Aidan 2026-04-24 04:42Z go-signal. Opus-orchestrated (Claude Code Opus
# 4.7 in-session) with verbose per-iteration stdout_tail dumps via
# ATH-563. ATH-562 still open — events journal until Sam merges.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$HERE/outputs/fleet_sweep_$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"
echo "[fleet-sweep] out_dir=$OUT_DIR" | tee "$OUT_DIR/README.txt"
for MODEL in \
    "anthropic/claude-sonnet-4-6" \
    "openai/kimi-k2.6-1" \
    "anthropic/claude-opus-4-7"
do
    SLUG="$(echo "$MODEL" | tr '/' '-')"
    LOG="$OUT_DIR/$SLUG.log"
    echo "=== [fleet-sweep] $(date -u +%H:%M:%SZ) launching $MODEL -> $LOG ==="
    EXP2_MODEL="$MODEL" python3 "$HERE/run_lm_palamedes_sampled.py" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}
    echo "=== [fleet-sweep] $(date -u +%H:%M:%SZ) $MODEL rc=$rc ==="
done
echo "[fleet-sweep] done. logs in $OUT_DIR"
