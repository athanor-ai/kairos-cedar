// Schema JSON round-trip probe — comprehensive.
//
// Documents:
// 1. cedar-go CANNOT parse Rust's bare CommonTypeRef form {"type": "Address"}
//    (unknown type error)
// 2. cedar-go CAN parse its own EntityOrCommon form
// 3. Rust re-emits CommonTypeRef as {"type": "Address"}, not EntityOrCommon
// 4. Cedar-text → JSON: both impls emit EntityOrCommon for unresolved TypeRefs
//    including built-in primitive names
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"

	"github.com/cedar-policy/cedar-go/x/exp/schema"
)

func main() {
	fmt.Println("== Schema JSON round-trip probe (cedar-go x/exp/schema) ==")

	// ──────────────────────────────────────────────────────────────────────────
	// PROBE 1: Can cedar-go parse Rust's CommonTypeRef form?
	// Rust emits {"type": "Address"} for references to the common type "Address".
	// cedar-go only handles: String, Long, Boolean, Extension, Set, Record,
	// Entity, EntityOrCommon. "Address" is none of these → parse error.
	// ──────────────────────────────────────────────────────────────────────────
	rustJSON := `{
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
}`

	fmt.Println("\n--- PROBE 1: Parse Rust CommonTypeRef bare form ---")
	fmt.Printf("  Input has {\"type\": \"Address\"} (the Rust native CommonTypeRef wire form)\n")
	var s1 schema.Schema
	if err := s1.UnmarshalJSON([]byte(rustJSON)); err != nil {
		fmt.Printf("  RESULT: PARSE ERROR — %v\n", err)
		fmt.Printf("  VERDICT: cedar-go cannot parse Rust-emitted schema JSON for CommonTypeRef\n")
	} else {
		fmt.Printf("  RESULT: OK (parsed successfully)\n")
		out, _ := s1.MarshalJSON()
		fmt.Printf("  Re-emitted: %s\n", truncate(string(out), 300))
	}

	// ──────────────────────────────────────────────────────────────────────────
	// PROBE 2: cedar-go → JSON → cedar-go round-trip (self-consistency)
	// ──────────────────────────────────────────────────────────────────────────
	goJSON := `{
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
}`

	fmt.Println("\n--- PROBE 2: cedar-go EntityOrCommon round-trip ---")
	var s2 schema.Schema
	if err := s2.UnmarshalJSON([]byte(goJSON)); err != nil {
		fmt.Printf("  PARSE ERROR: %v\n", err)
	} else {
		out, _ := s2.MarshalJSON()
		eq := bytes.Equal(normalizeJSON([]byte(goJSON)), normalizeJSON(out))
		fmt.Printf("  Parsed OK; round-trip identity: %v\n", eq)
	}

	// ──────────────────────────────────────────────────────────────────────────
	// PROBE 3: Cedar-text → JSON → Cedar-text → JSON stability
	// ──────────────────────────────────────────────────────────────────────────
	cedarText := `type Address = {
    street: String,
    zip: String
};

entity User {
    addr: Address
};

action View appliesTo {
    principal: [User],
    resource: [User]
};
`
	fmt.Println("\n--- PROBE 3: Cedar-text → JSON → Cedar-text → JSON ---")
	var s3 schema.Schema
	if err := s3.UnmarshalCedar([]byte(cedarText)); err != nil {
		fmt.Printf("  PARSE ERROR: %v\n", err)
	} else {
		json1, _ := s3.MarshalJSON()
		cedar1, _ := s3.MarshalCedar()
		fmt.Printf("  Cedar-text → JSON:\n  %s\n", truncate(string(json1), 500))
		fmt.Printf("  Cedar-text → Cedar-text:\n%s\n", string(cedar1))
		// Parse the JSON again
		var s3b schema.Schema
		if err := s3b.UnmarshalJSON(json1); err != nil {
			fmt.Printf("  ROUND-TRIP JSON parse error: %v\n", err)
		} else {
			json2, _ := s3b.MarshalJSON()
			stableJSON := bytes.Equal(normalizeJSON(json1), normalizeJSON(json2))
			fmt.Printf("  JSON stable: %v\n", stableJSON)
			// Parse Cedar-text output
			var s3c schema.Schema
			if err := s3c.UnmarshalCedar(cedar1); err != nil {
				fmt.Printf("  ROUND-TRIP Cedar-text parse error: %v\n", err)
			} else {
				cedar2, _ := s3c.MarshalCedar()
				stableCedar := bytes.Equal(cedar1, cedar2)
				fmt.Printf("  Cedar-text stable: %v\n", stableCedar)
			}
		}
	}

	// ──────────────────────────────────────────────────────────────────────────
	// PROBE 4: Cross-namespace entity type references
	// ──────────────────────────────────────────────────────────────────────────
	crossNsText := `namespace Acme {
    entity Document;
}

namespace Finance {
    entity Report in [Acme::Document] {
        owner: Acme::Document
    };

    action Read appliesTo {
        principal: [Finance::Report],
        resource: [Acme::Document]
    };
}
`
	fmt.Println("\n--- PROBE 4: Cross-namespace schema round-trip ---")
	var s4 schema.Schema
	if err := s4.UnmarshalCedar([]byte(crossNsText)); err != nil {
		fmt.Printf("  PARSE ERROR: %v\n", err)
	} else {
		json1, _ := s4.MarshalJSON()
		cedar1, _ := s4.MarshalCedar()
		fmt.Printf("  JSON: %s\n", truncate(string(json1), 300))
		fmt.Printf("  Cedar:\n%s\n", string(cedar1))
		var s4b schema.Schema
		if err := s4b.UnmarshalCedar(cedar1); err != nil {
			fmt.Printf("  ROUND-TRIP Cedar-text parse error: %v\n", err)
		} else {
			cedar2, _ := s4b.MarshalCedar()
			stable := bytes.Equal(cedar1, cedar2)
			fmt.Printf("  Cedar-text stable: %v\n", stable)
		}
	}

	// ──────────────────────────────────────────────────────────────────────────
	// PROBE 5: Schema with entity tags (Set<CommonType>)
	// ──────────────────────────────────────────────────────────────────────────
	tagsSchemaText := `type Tag = {
    key: String,
    value: String
};

entity Resource tags Set<Tag>;

action View appliesTo {
    principal: [Resource],
    resource: [Resource]
};
`
	fmt.Println("\n--- PROBE 5: Schema with entity tags using common type ---")
	var s5 schema.Schema
	if err := s5.UnmarshalCedar([]byte(tagsSchemaText)); err != nil {
		fmt.Printf("  PARSE ERROR: %v\n", err)
	} else {
		json1, _ := s5.MarshalJSON()
		cedar1, _ := s5.MarshalCedar()
		fmt.Printf("  JSON: %s\n", truncate(string(json1), 400))
		fmt.Printf("  Cedar: %s\n", truncate(string(cedar1), 200))
	}

	fmt.Println("\n== Done ==")
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}

func normalizeJSON(b []byte) []byte {
	var v interface{}
	if err := json.Unmarshal(b, &v); err != nil {
		return b
	}
	out, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return b
	}
	return out
}

func init() {
	_ = os.Stderr
}
