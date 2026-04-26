package main

import (
	"encoding/json"
	"fmt"

	"github.com/cedar-policy/cedar-go/types"
)

// Wire-format round-trip: feed cedar-go a JSON blob that a Rust impl could
// plausibly emit (explicit /32, /128) and re-emit JSON.  A byte-equal failure
// is a wire-format divergence.
func roundTrip(label string, in []byte) {
	var ip types.IPAddr
	if err := json.Unmarshal(in, &ip); err != nil {
		fmt.Println(label, "unmarshal:", err)
		return
	}
	out, _ := ip.MarshalJSON()
	fmt.Printf("%-30s in=%-50s  out=%-46s  byte-equal=%v\n",
		label, string(in), string(out), string(in) == string(out))
}

// Symmetric: also feed the dec extension blob.
func decRoundTrip(label string, in []byte) {
	var d types.Decimal
	if err := json.Unmarshal(in, &d); err != nil {
		fmt.Println(label, "unmarshal:", err)
		return
	}
	out, _ := d.MarshalJSON()
	fmt.Printf("%-30s in=%-50s  out=%-46s  byte-equal=%v\n",
		label, string(in), string(out), string(in) == string(out))
}

func main() {
	fmt.Println("== IPAddr wire-format round-trip on cedar-go ==")
	roundTrip("rust-style /32",
		[]byte(`{"__extn":{"fn":"ip","arg":"127.0.0.1/32"}}`))
	roundTrip("rust-style /128",
		[]byte(`{"__extn":{"fn":"ip","arg":"::1/128"}}`))
	roundTrip("rust-style /8 (true subnet)",
		[]byte(`{"__extn":{"fn":"ip","arg":"10.0.0.0/8"}}`))
	roundTrip("rust-style bare v4",
		[]byte(`{"__extn":{"fn":"ip","arg":"127.0.0.1"}}`))

	fmt.Println()
	fmt.Println("== Decimal wire-format round-trip on cedar-go ==")
	decRoundTrip("rust-style 1.2300",
		[]byte(`{"__extn":{"fn":"decimal","arg":"1.2300"}}`))
	decRoundTrip("rust-style 0.0010",
		[]byte(`{"__extn":{"fn":"decimal","arg":"0.0010"}}`))
	decRoundTrip("rust-style -0.1000",
		[]byte(`{"__extn":{"fn":"decimal","arg":"-0.1000"}}`))
	decRoundTrip("rust-style canonical 1.23",
		[]byte(`{"__extn":{"fn":"decimal","arg":"1.23"}}`))
}
