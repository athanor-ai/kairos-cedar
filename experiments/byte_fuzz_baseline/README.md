# byte_fuzz_baseline

Standalone byte-level fuzz harness for the [cedar-policy](https://crates.io/crates/cedar-policy) parser + evaluator. Provides a reproducible baseline for evaluating type-directed Cedar generators.

## Why this exists

A type-directed Cedar generator that ships "1.0 of generated tuples parse + evaluate" is meaningless without a byte-level reference. The standard byte-level reference for Cedar is the `simple-parser` / `abac-type-directed` fuzz targets in [cedar-spec/cedar-drt](https://github.com/cedar-policy/cedar-spec/tree/main/cedar-drt), but those depend on cargo-fuzz, libfuzzer, and the Lean FFI, so they do not run inside a typical Cedar consumer's CI.

This crate is a self-contained reimplementation of the same metric (bytes -> parser-reach + evaluator-reach + disagreement) using only the public `cedar-policy` API + `arbitrary`. It builds without cargo-fuzz; it runs anywhere the cedar-policy crate compiles.

It is **not** a drop-in replacement for cedar-drt. cedar-drt has libfuzzer's coverage-guided mutation; this binary uses uniform random bytes plus a corpus-mutation mode. The point is to give downstream Cedar tooling a uniform baseline that is comparable across environments.

## Modes

| Mode | What it does | Mirrors |
| :--- | :--- | :--- |
| `bytes` | Sample N random byte strings, attempt to parse as Cedar policyset, count parser-reach | cedar-drt `simple-parser` |
| `corpus-mutate` | Pick a random seed from a small valid-policy corpus, apply 1-3 byte-level mutations, parse + evaluate | cedar-drt `simple-parser` with corpus seeding |
| `arbitrary` | Reserved: `cedar-policy-generators` 4.0.0 does not compile against cedar 4.10. Re-enable when upstream fixes |

## Build + run

```bash
cd experiments/byte_fuzz_baseline
cargo build --release
./target/release/byte_fuzz_baseline --mode bytes --n 10000 --seed 42
./target/release/byte_fuzz_baseline --mode corpus-mutate --n 10000 --seed 42
```

Output is one JSONL line per attempt plus a summary line. Use `--only-emit-parsed` to suppress non-parsed attempts.

## Reproducibility

`--seed` pins both the byte-string RNG and the corpus-pick RNG (both `ChaCha20`). Two runs with the same seed produce byte-identical output, modulo `elapsed_ms`.

## License

Apache-2.0. See top-level `LICENSE`.
