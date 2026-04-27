# 04-type-directed-diff-test

Sample N policy / schema / request tuples from the type-directed Lean generator (`cedar-full/CedarFull/PolicyGen.lean`) and decide each via cedar-policy (Rust) and cedar-go in parallel. Report agreement rate, disagreement rate, and per-tuple cost. This is the §8 differential pipeline that the kairos-cedar paper reports at N=10,000.

## Files

* `run.sh`: invokes `experiments/phase_c_diff/run_diff.py` with `--no-session` (license-free local mode) and N=20.

## Run

From the **host** (not inside the dev container — this driver script orchestrates docker run calls under the hood, so it needs docker on PATH):

```bash
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
cd examples/04-type-directed-diff-test
./run.sh
```

Expected (warm Lean cache, ~30 seconds):

```
N sampled          : 20
Valid-sample rate  : 1.000  (20/20 Go non-error)
Pairs compared     : 20
Agreement rate     : 1.0000  (20/20)
Disagreement count : 0
```

Pass `--n 1000` (and a longer timeout) if you want to reproduce a richer run; the §8 paper table is N=10,000 and takes about 2 minutes.

## What this exercises

* `genPolicy` from `cedar-full/CedarFull/PolicyGen.lean` (42 well-typed policy shapes).
* The Go diff driver under `experiments/phase_c_diff/go_harness/`.
* The Rust `cedar authorize` CLI.

## How to use against your own policies

The `--policies` and `--schema` flags on `experiments/phase_c_diff/run_diff.py` take the same JSON shapes as the upstream Cedar test corpus. Drop your own schema in, point the runner at it, and you have a type-directed differential test of cedar-go against cedar-policy on your shape.

## License

Apache-2.0. See top-level `LICENSE`.
