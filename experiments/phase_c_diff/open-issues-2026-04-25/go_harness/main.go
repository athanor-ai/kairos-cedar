package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	cedar "github.com/cedar-policy/cedar-go"
	"github.com/cedar-policy/cedar-go/types"
)

type TupleReq struct {
	Idx       string `json:"idx"`
	Principal string `json:"principal"`
	Action    string `json:"action"`
	Resource  string `json:"resource"`
	Policy    string `json:"policy"`
}

type Result struct {
	Idx        string `json:"idx"`
	Decision   string `json:"decision"`
	Error      string `json:"error,omitempty"`
	Diagnostic string `json:"diagnostic,omitempty"`
}

func parseUID(s string) (types.EntityUID, error) {
	idx := strings.Index(s, "::")
	if idx < 0 {
		return types.EntityUID{}, fmt.Errorf("bad UID: %q", s)
	}
	ty := types.EntityType(s[:idx])
	eid := types.String(s[idx+2:])
	return types.NewEntityUID(ty, eid), nil
}

func main() {
	entitiesPath := os.Args[1]
	entitiesData, err := os.ReadFile(entitiesPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "entities read:", err)
		os.Exit(2)
	}
	var entities types.EntityMap
	if err := json.Unmarshal(entitiesData, &entities); err != nil {
		entities = types.EntityMap{}
	}

	enc := json.NewEncoder(os.Stdout)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024*1024), 64*1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var t TupleReq
		if err := json.Unmarshal([]byte(line), &t); err != nil {
			enc.Encode(Result{Idx: "?", Error: fmt.Sprintf("parse: %v", err)})
			continue
		}
		ps, err := parseUID(t.Principal)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("principal: %v", err)})
			continue
		}
		act, err := parseUID(t.Action)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("action: %v", err)})
			continue
		}
		res, err := parseUID(t.Resource)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("resource: %v", err)})
			continue
		}
		policies, err := cedar.NewPolicySetFromBytes("policy.cedar", []byte(t.Policy))
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Decision: "ERROR", Error: fmt.Sprintf("policy parse: %v", err)})
			continue
		}
		req := cedar.Request{
			Principal: ps,
			Action:    act,
			Resource:  res,
			Context:   types.NewRecord(nil),
		}
		dec, diag := policies.IsAuthorized(entities, req)
		decision := "Deny"
		if dec == cedar.Allow {
			decision = "Allow"
		}
		// capture eval errors as "diagnostic"
		var diagStr string
		for _, e := range diag.Errors {
			diagStr += e.Message + "; "
		}
		enc.Encode(Result{Idx: t.Idx, Decision: decision, Diagnostic: diagStr})
	}
}
