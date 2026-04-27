# 01-basic-rbac

Smallest working Cedar example. Three policies, three entity types, six requests.

## Files

* `schema.cedarschema`: entity types (`User`, `Role`, `Document`) and actions (`read`, `edit`, `publish`).
* `policy.cedar`: three policies. Admins do anything; confidential resources cannot be read; editors edit what they own.
* `entities.json`: five entities (alice the admin, bob the editor, carol with no role, two documents).
* `requests.jsonl`: six labelled requests with the decision we expect from each.

## Run

Inside the kairos-cedar dev container:

```bash
cd examples/01-basic-rbac
./run.sh
```

Or directly with `cedar` if you have `cedar-policy-cli` 4.10 installed locally:

```bash
cedar authorize \
  --schema schema.cedarschema \
  --policies policy.cedar \
  --entities entities.json \
  --principal 'User::"alice"' \
  --action 'Action::"read"' \
  --resource 'Document::"bobs_draft"'
```

Expected: `ALLOW`. Run again with `User::"bob"`, `Action::"read"`, `Document::"secret_memo"` and you should see `DENY` (the `deny-confidential-read` policy fires).

## What this exercises

* `permit` / `forbid` precedence.
* Role hierarchy via `principal in Role::"admin"`.
* Attribute conditions via `resource.tag == "confidential"`.
* Type guards via `resource is Document`.

These are the four shape classes that the kairos-cedar differential pipeline (see `experiments/phase_c_diff/`) cross-checks between cedar-policy (Rust) and cedar-go.

## License

Apache-2.0. See top-level `LICENSE`.
