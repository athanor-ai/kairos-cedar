package main

// Issue 1702 reproducer for cedar-go: JSON schema with all-common-type
// entity attrs round-tripping through cedar-go's experimental schema
// package.
//
// The JSON form is the one in https://github.com/cedar-policy/cedar/issues/1702 .
// We parse it via cedar-go x/exp/schema, then try to MarshalCedar back to
// human-readable form, and compare to what `cedar translate-schema --direction
// json-to-cedar` does in the Rust reference.

import (
	"fmt"
	"os"

	"github.com/cedar-policy/cedar-go/x/exp/schema"
)

func main() {
	jsonPath := os.Args[1]
	jsonBytes, err := os.ReadFile(jsonPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		os.Exit(2)
	}
	var s schema.Schema
	if err := s.UnmarshalJSON(jsonBytes); err != nil {
		fmt.Println("UNMARSHAL_JSON_ERROR:", err)
		os.Exit(0)
	}
	fmt.Println("UNMARSHAL_JSON_OK")
	cedarBytes, err := s.MarshalCedar()
	if err != nil {
		fmt.Println("MARSHAL_CEDAR_ERROR:", err)
		os.Exit(0)
	}
	fmt.Println("MARSHAL_CEDAR_OK")
	fmt.Println("--- BEGIN MARSHALLED CEDAR ---")
	fmt.Print(string(cedarBytes))
	fmt.Println("--- END MARSHALLED CEDAR ---")

	// Now try the round-trip: parse the marshalled Cedar back.
	var s2 schema.Schema
	if err := s2.UnmarshalCedar(cedarBytes); err != nil {
		fmt.Println("ROUNDTRIP_REPARSE_ERROR:", err)
		os.Exit(0)
	}
	fmt.Println("ROUNDTRIP_REPARSE_OK")
}
