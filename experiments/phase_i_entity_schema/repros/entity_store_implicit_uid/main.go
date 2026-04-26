// Datetime policy-decision test.
//
// Confirms that the datetime wire normalization bug does NOT affect
// policy decisions — just wire format. Uses cedar-go's Authorize
// function to check that datetime("T00:00:00Z") == datetime("T00:00:00.000Z")
// for comparison purposes.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	cedar "github.com/cedar-policy/cedar-go"
	"github.com/cedar-policy/cedar-go/types"
)

func main() {
	fmt.Println("== Datetime policy-decision test (cedar-go) ==")

	// Policy: permit if resource.created_at < datetime("2025-01-01T00:00:00.000Z")
	policyText := `permit(principal, action, resource)
when { resource.created_at < datetime("2025-01-01T00:00:00.000Z") };`

	ps, err := cedar.NewPolicySetFromBytes("policy.cedar", []byte(policyText))
	if err != nil {
		fmt.Printf("FAIL policy parse: %v\n", err)
		os.Exit(1)
	}

	// Entity with created_at = "2024-01-15T00:00:00Z" (no ms — the Rust wire form)
	entityJSON1 := `[{
		"uid": {"type": "Resource", "id": "doc1"},
		"parents": [],
		"attrs": {"created_at": {"__extn": {"fn": "datetime", "arg": "2024-01-15T00:00:00Z"}}},
		"tags": {}
	}, {
		"uid": {"type": "User", "id": "alice"},
		"parents": [],
		"attrs": {},
		"tags": {}
	}]`

	// Entity with created_at = "2024-01-15T00:00:00.000Z" (with ms — the cedar-go re-emit form)
	entityJSON2 := `[{
		"uid": {"type": "Resource", "id": "doc1"},
		"parents": [],
		"attrs": {"created_at": {"__extn": {"fn": "datetime", "arg": "2024-01-15T00:00:00.000Z"}}},
		"tags": {}
	}, {
		"uid": {"type": "User", "id": "alice"},
		"parents": [],
		"attrs": {},
		"tags": {}
	}]`

	req := cedar.Request{
		Principal: types.EntityUID{Type: "User", ID: "alice"},
		Action:    types.EntityUID{Type: "Action", ID: "view"},
		Resource:  types.EntityUID{Type: "Resource", ID: "doc1"},
	}

	for i, ejson := range []string{entityJSON1, entityJSON2} {
		var em types.EntityMap
		if err := json.Unmarshal([]byte(ejson), &em); err != nil {
			fmt.Printf("  [entity%d] FAIL UnmarshalJSON: %v\n", i+1, err)
			continue
		}
		decision, diag := cedar.Authorize(ps, em, req)
		label := "no-ms (Rust wire form)"
		if i == 1 {
			label = "with-.000ms (cedar-go re-emit)"
		}
		fmt.Printf("  [%-30s] decision=%v  errors=%d\n",
			label, decision, len(diag.Errors))
	}

	fmt.Println("\n  NOTE: Both should ALLOW — same millisecond value different string")
	fmt.Println("\n== Done ==")
}

func init() {
	_ = os.Stderr
}
