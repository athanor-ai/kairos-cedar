package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/cedar-policy/cedar-go/types"
)

// Print-table for one parsed decimal literal.
func dump(label, lit string) {
	d, err := types.ParseDecimal(lit)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse %q failed: %v\n", lit, err)
		return
	}
	mc := string(d.MarshalCedar())
	mj, err := d.MarshalJSON()
	if err != nil {
		fmt.Fprintf(os.Stderr, "marshalJSON %q failed: %v\n", lit, err)
		return
	}
	fmt.Printf("%-22s input=%-12q  String()=%-10q  MarshalCedar()=%-22q  MarshalJSON()=%s\n",
		label, lit, d.String(), mc, string(mj))
}

func main() {
	cases := []struct{ label, lit string }{
		{"trailing-zeros", "1.2300"},
		{"smallest-frac", "0.0010"},
		{"negative", "-0.1000"},
		{"all-four", "12.3400"},
		{"genuine-integer-form", "5"},     // input has no fractional part
		{"int-with-zeros", "5.0000"},
		{"already-canonical", "1.23"},
	}
	fmt.Println("== cedar-go Decimal: Display / MarshalCedar / MarshalJSON ==")
	for _, c := range cases {
		dump(c.label, c.lit)
	}

	// Round-trip check: parse "1.2300" -> JSON-marshal -> JSON-unmarshal -> re-marshal.
	d, _ := types.ParseDecimal("1.2300")
	bs, _ := json.Marshal(d)
	var d2 types.Decimal
	if err := json.Unmarshal(bs, &d2); err != nil {
		fmt.Fprintln(os.Stderr, "unmarshal:", err)
		return
	}
	bs2, _ := json.Marshal(d2)
	fmt.Printf("\nround-trip JSON of 1.2300: first=%s  second=%s  equal=%v\n",
		string(bs), string(bs2), string(bs) == string(bs2))
}
