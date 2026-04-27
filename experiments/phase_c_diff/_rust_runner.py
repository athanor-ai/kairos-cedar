
import json, subprocess, sys, os

sys.path.insert(0, "/work")
from experiments.lib.cedar_cli import parse_cedar_cli_result

input_path = "/work/experiments/phase_c_diff/_rust_input.jsonl"
schema_file = sys.argv[1]
entities_file = sys.argv[2]

lines = open(input_path).readlines()
for line in lines:
    line = line.strip()
    if not line:
        continue
    t = json.loads(line)
    idx = t["idx"]
    policy = t["policy"]
    p_parts = t["principal"].split("::")
    a_parts = t["action"].split("::")
    r_parts = t["resource"].split("::")

    pol_path = f"/tmp/pol_{idx}.cedar"
    with open(pol_path, "w") as f:
        f.write(policy)

    p_str = f'{p_parts[0]}::"{p_parts[1]}"'
    a_str = f'{a_parts[0]}::"{a_parts[1]}"'
    r_str = f'{r_parts[0]}::"{r_parts[1]}"'

    cmd = [
        "cedar", "authorize",
        "--policies", pol_path,
        "--entities", entities_file,
        "--schema", schema_file,
        "--request-validation", "false",
        "--principal", p_str,
        "--action", a_str,
        "--resource", r_str,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    parsed = parse_cedar_cli_result(result)
    # V1 policies are generator-validated well-typed, so ParseError /
    # EvalError shouldn't occur. We collapse to {Allow, Deny} for the
    # agreement rate; richer per-tuple bucketing lives in the widened
    # harness (run_widened.py).
    decision = parsed.decision_outcome
    print(f"{idx}\t{decision}", flush=True)
