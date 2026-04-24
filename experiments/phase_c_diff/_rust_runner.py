
import json, subprocess, sys, os

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
    txt = (result.stdout + result.stderr).upper()
    if "ALLOW" in txt:
        decision = "Allow"
    elif "DENY" in txt:
        decision = "Deny"
    else:
        decision = "ERROR(" + (result.stdout + result.stderr).strip()[:40] + ")"
    print(f"{idx}\t{decision}", flush=True)
