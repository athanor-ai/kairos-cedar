// decimal_repro.rs — reproduce Display / canonical / JSON behaviour of
// cedar-policy's `decimal` extension. Pinned to the cedar-policy workspace
// at /work/cedar-spec/cedar/cedar-policy (cedar-policy 4.10.0).

use cedar_policy::{Entities, EntityUid, EvalResult, Request, eval_expression};
use std::str::FromStr;

fn dump(label: &str, lit: &str) {
    let entities = Entities::empty();
    let p = EntityUid::from_str(r#"User::"a""#).unwrap();
    let a = EntityUid::from_str(r#"Action::"x""#).unwrap();
    let r = EntityUid::from_str(r#"Doc::"d""#).unwrap();
    let req = Request::new(p, a, r, cedar_policy::Context::empty(), None).unwrap();

    let expr_text = format!("decimal(\"{lit}\")");
    let expr = cedar_policy::Expression::from_str(&expr_text).unwrap();

    match eval_expression(&req, &entities, &expr) {
        Ok(EvalResult::ExtensionValue(s)) => {
            println!("{label:<22} input={lit:<12}  EvalResult::Display={s:?}");
        }
        Ok(other) => println!("{label}: unexpected EvalResult={other:?}"),
        Err(e) => println!("{label}: eval error: {e}"),
    }
}

fn dump_json_roundtrip(lit: &str) {
    // Build entities JSON with a decimal extension attribute, parse it via
    // Entities::from_json_str, then re-serialize to JSON.  Confirms the
    // round-trip representation (== "wire format") for cedar-policy 4.10.0.
    let json = format!(
        r#"[
  {{
    "uid": {{"type":"User","id":"alice"}},
    "attrs": {{
      "balance": {{"__extn": {{"fn":"decimal","arg":"{lit}"}}}}
    }},
    "parents": []
  }}
]"#
    );
    let entities = Entities::from_json_str(&json, None).unwrap();
    let serialized = entities.to_json_value().unwrap();
    let pretty = serde_json::to_string(&serialized).unwrap();
    println!("round-trip {lit:>10}: {pretty}");
}

fn main() {
    println!("== cedar-policy 4.10.0 (workspace pin) Decimal extension ==");
    for &lit in &[
        "1.2300", "0.0010", "-0.1000", "12.3400", "5.0000", "1.23",
    ] {
        dump(lit, lit);
    }
    println!();
    println!("== Entities round-trip JSON (input -> from_json -> to_json) ==");
    for &lit in &["1.2300", "0.0010", "-0.1000", "12.3400", "5.0000", "1.23"] {
        dump_json_roundtrip(lit);
    }
}
