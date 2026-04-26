
import json, subprocess, sys

input_path = sys.argv[1]
schema_file = sys.argv[2]
entities_file = sys.argv[3]

for line in open(input_path):
    line = line.strip()
    if not line:
        continue
    t = json.loads(line)
    idx = t["idx"]
    p_parts = t["principal"].split("::")
    a_parts = t["action"].split("::")
    r_parts = t["resource"].split("::")
    pol_path = "/tmp/pol_n100k.cedar"
    with open(pol_path, "w") as f:
        f.write(t["policy"])
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
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    txt = (res.stdout + res.stderr).strip()
    txtu = txt.upper()
    if "ALLOW" in txtu:
        decision = "Allow"
    elif "DENY" in txtu:
        decision = "Deny"
    else:
        decision = "ERROR"
    out = {
        "idx": idx,
        "decision": decision,
        "stdout_tail": res.stdout[-400:],
        "stderr_tail": res.stderr[-400:],
        "returncode": res.returncode,
    }
    print(json.dumps(out), flush=True)
