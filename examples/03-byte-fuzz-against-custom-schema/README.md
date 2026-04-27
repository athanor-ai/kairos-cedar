# 03-byte-fuzz-against-custom-schema

Run the `byte_fuzz_baseline` driver against the cedar-policy parser to measure parser-reach + evaluator-reach on uniform random byte input. This is the byte-level reference that any type-directed Cedar generator should be compared against.

## Files

* `run.sh`: builds `byte_fuzz_baseline`, runs 1,000 random-byte attempts in `bytes` mode, prints the parser-reach rate.

## Run

Inside the kairos-cedar dev container:

```bash
cd examples/03-byte-fuzz-against-custom-schema
./run.sh
```

Expected: a line of the form

```
DONE attempts=1000 parsed=N evaluated=M elapsed=...
```

where `N` is the number of random-byte inputs that parsed as Cedar policysets and `M` is the number that also reached the evaluator. Typical values: parser-reach ~0.0005 (5 in 10,000) under `bytes` mode, ~0.05 (1 in 20) under `corpus-mutate` mode with a small valid-policy seed corpus.

## Why this matters

A type-directed Cedar generator that ships "1.0 of generated tuples parse + evaluate" is meaningless without a byte-level reference. `byte_fuzz_baseline` is the comparable harness: same metric, no cargo-fuzz / libfuzzer / Lean FFI required.

For the source plus the full mode set (`bytes`, `corpus-mutate`, `arbitrary`-reserved), see `experiments/byte_fuzz_baseline/README.md`.

## License

Apache-2.0. See top-level `LICENSE`.
