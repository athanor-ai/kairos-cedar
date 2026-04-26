package main

import (
	"encoding/json"
	"fmt"

	cedar "github.com/cedar-policy/cedar-go"
	"github.com/cedar-policy/cedar-go/types"
)

const policy = `permit(principal, action, resource) when {
  resource.balance == decimal("1.2300")
};
`

func runOne(label, attrJSON string) {
	entitiesJSON := fmt.Sprintf(`[
  {"uid":{"type":"User","id":"alice"},"attrs":{},"parents":[]},
  {"uid":{"type":"Doc","id":"d"},"attrs":{"balance":%s},"parents":[]}
]`, attrJSON)

	var entities types.EntityMap
	if err := json.Unmarshal([]byte(entitiesJSON), &entities); err != nil {
		fmt.Println(label, "entities:", err)
		return
	}

	ps, err := cedar.NewPolicySetFromBytes("policy.cedar", []byte(policy))
	if err != nil {
		fmt.Println(label, "policy parse:", err)
		return
	}
	req := cedar.Request{
		Principal: types.NewEntityUID("User", "alice"),
		Action:    types.NewEntityUID("Action", "x"),
		Resource:  types.NewEntityUID("Doc", "d"),
		Context:   types.NewRecord(nil),
	}
	dec, _ := ps.IsAuthorized(entities, req)
	fmt.Printf("%-32s decision=%v\n", label, dec)
}

func main() {
	runOne(`canonical-arg "1.23"`, `{"__extn":{"fn":"decimal","arg":"1.23"}}`)
	runOne(`padded-arg "1.2300"`, `{"__extn":{"fn":"decimal","arg":"1.2300"}}`)
}
