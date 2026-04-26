// ipaddr_repro.rs — reproduce Display / canonical / JSON behaviour of
// cedar-policy's `ip` extension. Pinned to cedar-policy 4.10.0 via the
// /work/cedar-spec/cedar workspace.

use cedar_policy::{Entities, EntityUid, EvalResult, Expression, Request, eval_expression};
use std::str::FromStr;

fn dump(label: &str, lit: &str) {
    let entities = Entities::empty();
    let p = EntityUid::from_str(r#"User::"a""#).unwrap();
    let a = EntityUid::from_str(r#"Action::"x""#).unwrap();
    let r = EntityUid::from_str(r#"Doc::"d""#).unwrap();
    let req =
        Request::new(p, a, r, cedar_policy::Context::empty(), None).unwrap();

    let expr_text = format!("ip(\"{lit}\")");
    let expr = Expression::from_str(&expr_text).unwrap();

    match eval_expression(&req, &entities, &expr) {
        Ok(EvalResult::ExtensionValue(s)) => {
            println!("{label:<22} input={lit:<18}  EvalResult::Display={s:?}");
        }
        Ok(other) => println!("{label}: unexpected EvalResult={other:?}"),
        Err(e) => println!("{label}: eval error: {e}"),
    }
}

fn dump_json_roundtrip(lit: &str) {
    let json = format!(
        r#"[
  {{
    "uid": {{"type":"User","id":"alice"}},
    "attrs": {{
      "src": {{"__extn": {{"fn":"ip","arg":"{lit}"}}}}
    }},
    "parents": []
  }}
]"#
    );
    let entities = Entities::from_json_str(&json, None).unwrap();
    let serialized = entities.to_json_value().unwrap();
    let pretty = serde_json::to_string(&serialized).unwrap();
    println!("round-trip {lit:>16}: {pretty}");
}

fn main() {
    println!("== cedar-policy 4.10.0 (workspace pin) IPAddr extension ==");
    for &lit in &[
        "127.0.0.1",
        "127.0.0.1/32",
        "10.0.0.0/8",
        "::1",
        "::1/128",
        "2001:db8::/32",
    ] {
        dump(lit, lit);
    }
    println!();
    println!("== Entities round-trip JSON (input -> from_json -> to_json) ==");
    for &lit in &["127.0.0.1", "127.0.0.1/32", "10.0.0.0/8", "::1", "::1/128"] {
        dump_json_roundtrip(lit);
    }
}
