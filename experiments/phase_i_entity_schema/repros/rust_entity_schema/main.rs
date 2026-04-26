// Rust entity-store and schema probe for kairos-cedar bug hunt.
//
// Tests:
// 1. Schema JSON: CommonTypeRef form (bare type name as "type" field) - Rust emit
// 2. Schema JSON: EntityOrCommon form (cedar-go format) - Rust parse
// 3. Schema Cedar-text → JSON
// 4. datetime wire normalization in entity attributes
// 5. Implicit entity ref in attribute
//
// Uses cedar-policy 4.10.0 from /work/cedar-spec/cedar/cedar-policy.
use cedar_policy::{Entities, SchemaFragment};

fn main() {
    println!("== Rust cedar-policy entity-store + schema probe ==");

    // ── Schema tests ──
    println!("\n--- Schema Test 1: CommonTypeRef bare form (Rust native parse+emit) ---");
    let rust_schema_json = r#"{
  "": {
    "commonTypes": {
      "Address": {
        "type": "Record",
        "attributes": {
          "street": {"type": "String"},
          "zip": {"type": "String"}
        }
      }
    },
    "entityTypes": {
      "User": {
        "shape": {
          "type": "Record",
          "attributes": {
            "addr": {"type": "Address"}
          }
        }
      }
    },
    "actions": {}
  }
}"#;
    match SchemaFragment::from_json_str(rust_schema_json) {
        Ok(schema) => {
            println!("  OK: Parsed CommonTypeRef bare form");
            match schema.to_json_value() {
                Ok(v) => {
                    let out = serde_json::to_string_pretty(&v).unwrap();
                    let has_bare = out.contains("\"type\": \"Address\"");
                    let has_eoc = out.contains("\"EntityOrCommon\"");
                    println!("  Re-emits bare 'Address' (CommonTypeRef form): {}", has_bare);
                    println!("  Re-emits 'EntityOrCommon': {}", has_eoc);
                    println!("  === FULL OUTPUT ===\n{}\n==================", out);
                }
                Err(e) => println!("  FAIL to_json_value: {:?}", e),
            }
        }
        Err(e) => println!("  FAIL: Parse error: {:?}", e),
    }

    println!("\n--- Schema Test 2: EntityOrCommon explicit tag (cedar-go format) → Rust parse+emit ---");
    let go_schema_json = r#"{
  "": {
    "commonTypes": {
      "Address": {
        "type": "Record",
        "attributes": {
          "street": {"type": "String"},
          "zip": {"type": "String"}
        }
      }
    },
    "entityTypes": {
      "User": {
        "shape": {
          "type": "Record",
          "attributes": {
            "addr": {"type": "EntityOrCommon", "name": "Address"}
          }
        }
      }
    },
    "actions": {}
  }
}"#;
    match SchemaFragment::from_json_str(go_schema_json) {
        Ok(schema) => {
            println!("  OK: Parsed EntityOrCommon form");
            match schema.to_json_value() {
                Ok(v) => {
                    let out = serde_json::to_string_pretty(&v).unwrap();
                    let has_bare = out.contains("\"type\": \"Address\"");
                    let has_eoc = out.contains("\"EntityOrCommon\"");
                    println!("  Re-emits bare 'Address': {}", has_bare);
                    println!("  Re-emits 'EntityOrCommon': {}", has_eoc);
                    println!("  === FULL OUTPUT ===\n{}\n==================", out);
                }
                Err(e) => println!("  FAIL to_json_value: {:?}", e),
            }
        }
        Err(e) => println!("  FAIL: Parse error: {:?}", e),
    }

    println!("\n--- Schema Test 3: Cedar-text schema → JSON emit ---");
    let cedar_text = r#"type Address = {
    street: String,
    zip: String
};

entity User {
    addr: Address
};

action View appliesTo {
    principal: [User],
    resource: [User]
};"#;
    match SchemaFragment::from_cedarschema_str(cedar_text) {
        Ok((schema, _warnings)) => {
            println!("  OK: Parsed Cedar text");
            match schema.to_json_value() {
                Ok(v) => {
                    let out = serde_json::to_string_pretty(&v).unwrap();
                    let has_bare_addr = out.contains("\"type\": \"Address\"");
                    let has_eoc_addr = out.contains("\"EntityOrCommon\"");
                    let has_bare_str = out.contains("\"type\": \"String\"");
                    println!("  Bare 'Address': {}  EntityOrCommon: {}  Bare 'String': {}", has_bare_addr, has_eoc_addr, has_bare_str);
                    println!("  === FULL OUTPUT ===\n{}\n==================", out);
                }
                Err(e) => println!("  FAIL to_json_value: {:?}", e),
            }
        }
        Err(e) => println!("  FAIL: {:?}", e),
    }

    // ── Entity store + datetime tests ──
    println!("\n--- Entity Test: datetime wire normalization ---");
    let cases = vec![
        ("bare-zulu-no-ms", "2024-01-15T00:00:00Z"),
        ("bare-zulu-with-time", "2024-01-15T12:30:45Z"),
        ("with-ms-already", "2024-01-15T00:00:00.123Z"),
        ("midnight-utc", "2000-01-01T00:00:00Z"),
        ("max-ms", "2024-06-15T23:59:59.999Z"),
    ];
    for (label, dt_input) in cases {
        let entity_json = format!(
            r#"[{{"uid":{{"type":"X","id":"x"}},"parents":[],"attrs":{{"t":{{"__extn":{{"fn":"datetime","arg":"{}"}}}}}},"tags":{{}}}}]"#,
            dt_input
        );
        match Entities::from_json_str(&entity_json, None) {
            Ok(entities) => {
                match entities.to_json_value() {
                    Ok(v) => {
                        let out = serde_json::to_string(&v).unwrap();
                        // Extract the arg from the output
                        let marker = r#""arg":""#;
                        let out_arg = if let Some(pos) = out.find(marker) {
                            let after = &out[pos + marker.len()..];
                            if let Some(end) = after.find('"') {
                                &after[..end]
                            } else {
                                ""
                            }
                        } else {
                            ""
                        };
                        let eq = dt_input == out_arg;
                        if !eq {
                            println!("  [{:<30}] DIVERGE: input={:?}  output={:?}  byte-equal={}",
                                label, dt_input, out_arg, eq);
                        } else {
                            println!("  [{:<30}] OK: input={:?} preserved", label, dt_input);
                        }
                    }
                    Err(e) => println!("  [{:<30}] FAIL to_json_value: {:?}", label, e),
                }
            }
            Err(e) => println!("  [{:<30}] FAIL parse: {:?}", label, e),
        }
    }

    println!("\n--- Entity Test: Implicit entity ref in attribute ---");
    let implicit_json = r#"[{"uid":{"type":"User","id":"alice"},"parents":[],"attrs":{"manager":{"type":"User","id":"bob"},"score":42},"tags":{}}]"#;
    match Entities::from_json_str(implicit_json, None) {
        Ok(entities) => {
            println!("  OK: parsed {} entities", entities.iter().count());
            match entities.to_json_value() {
                Ok(v) => {
                    let out = serde_json::to_string_pretty(&v).unwrap();
                    let has_entity = out.contains("__entity");
                    let has_type_user = out.contains("\"type\": \"User\"");
                    println!("  manager attr becomes __entity: {}", has_entity);
                    println!("  manager attr stays as {{type,id}} Record: {}", has_type_user);
                    println!("  === FULL OUTPUT ===\n{}\n==================", out);
                }
                Err(e) => println!("  FAIL to_json_value: {:?}", e),
            }
        }
        Err(e) => println!("  FAIL: {:?}", e),
    }

    println!("\n== Done ==");
}
