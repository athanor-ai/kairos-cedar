"""Shared helpers for the experiments/ harnesses.

Modules here are imported by both experiments/phase_c_diff/run_diff.py
and (when present) the widened-shapes harness, so the cedar-CLI result
parsing, version pin reading, and other invariants are asserted in
exactly one place.
"""
