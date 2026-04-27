# Examples

Four self-contained examples covering the four things a Cedar consumer typically wants from this repo. Each example lives in its own folder with a short README, the input fixtures, and a `run.sh` you can invoke inside the kairos-cedar dev container.

## How to run

```bash
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
```

* Examples 01, 02, 03 run **inside** the dev container:
  ```bash
  ./scripts/dc bash -c "cd examples/01-basic-rbac && bash run.sh"
  ```
* Example 04 runs **on the host** (its driver orchestrates docker run calls under the hood):
  ```bash
  cd examples/04-type-directed-diff-test && ./run.sh
  ```

## What each example shows

| Folder | What it shows | Toolchain |
| :----- | :----- | :----- |
| `01-basic-rbac` | Smallest working Cedar setup. Three policies, six labelled requests, end-to-end via `cedar authorize` | cedar-policy-cli 4.10 |
| `02-symcc-never-errors` | Property verification: prove a policy never errors at runtime via `cedar symcc` and CVC5 | cedar-policy-cli 4.10 with `--features analyze` plus CVC5 1.3.1 |
| `03-byte-fuzz-against-custom-schema` | Byte-level fuzz baseline: parser-reach + evaluator-reach on uniform random byte input. The reference any type-directed Cedar generator should be compared against | Rust + cedar-policy 4.10 |
| `04-type-directed-diff-test` | The §8 type-directed differential pipeline: sample N well-typed policy / schema / request tuples from a Lean generator, decide each via cedar-policy (Rust) and cedar-go, report agreement rate | Lean 4.29.1, cedar-policy 4.10, cedar-go HEAD |

Examples 01 and 02 are the cheap ones (a few seconds each); 03 takes ~30 seconds; 04 takes ~30 seconds with a warm Lean cache and a few minutes from a cold start.

## More

* The end-to-end demo (`demo/run_demo.py`) chains examples 01, 04, plus the cedar-go corpus test and the Lean bridge build. Run it for a full smoke of every signal the repo offers.
* `docs/symcc-walkthrough.md` is the longer-form companion to example 02.
* `experiments/byte_fuzz_baseline/` is the source for the driver in example 03.
* `experiments/phase_c_diff/` is the source for the runner in example 04.

## License

Apache-2.0. See top-level `LICENSE`.
