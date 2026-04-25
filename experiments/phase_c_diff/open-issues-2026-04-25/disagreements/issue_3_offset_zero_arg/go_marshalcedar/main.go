package main

// Probe issue 2116 in cedar-go: parse JSON policy with `{"offset":[]}`,
// then MarshalCedar back to text. Compare to what `cedar translate-policy`
// emits.

import (
	"fmt"
	"os"

	cedar "github.com/cedar-policy/cedar-go"
)

func main() {
	jsonPath := os.Args[1]
	b, err := os.ReadFile(jsonPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		os.Exit(2)
	}
	var p cedar.Policy
	if err := p.UnmarshalJSON(b); err != nil {
		fmt.Println("UNMARSHAL_JSON_ERROR:", err)
		os.Exit(0)
	}
	fmt.Println("UNMARSHAL_JSON_OK")
	out := p.MarshalCedar()
	fmt.Println("--- BEGIN MARSHALLED CEDAR ---")
	fmt.Print(string(out))
	fmt.Println("\n--- END MARSHALLED CEDAR ---")

	// Round-trip: re-parse the marshalled text.
	var p2 cedar.Policy
	if err := p2.UnmarshalCedar(out); err != nil {
		fmt.Println("ROUNDTRIP_REPARSE_ERROR:", err)
		os.Exit(0)
	}
	fmt.Println("ROUNDTRIP_REPARSE_OK")
}
