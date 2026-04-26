package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/cedar-policy/cedar-go/types"
)

func dump(label, lit string) {
	ip, err := types.ParseIPAddr(lit)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse %q failed: %v\n", lit, err)
		return
	}
	mc := string(ip.MarshalCedar())
	mj, err := ip.MarshalJSON()
	if err != nil {
		fmt.Fprintf(os.Stderr, "marshalJSON %q failed: %v\n", lit, err)
		return
	}
	fmt.Printf("%-22s input=%-18q  String()=%-18q  MarshalCedar()=%-26q  MarshalJSON()=%s\n",
		label, lit, ip.String(), mc, string(mj))
}

func main() {
	cases := []struct{ label, lit string }{
		{"v4-bare", "127.0.0.1"},
		{"v4-32", "127.0.0.1/32"},
		{"v4-net", "10.0.0.0/8"},
		{"v6-bare", "::1"},
		{"v6-128", "::1/128"},
		{"v6-net", "2001:db8::/32"},
	}
	fmt.Println("== cedar-go IPAddr: Display / MarshalCedar / MarshalJSON ==")
	for _, c := range cases {
		dump(c.label, c.lit)
	}

	// Round-trip: 127.0.0.1 (bare).  Show that JSON form omits the prefix.
	ip, _ := types.ParseIPAddr("127.0.0.1")
	bs, _ := json.Marshal(ip)
	var ip2 types.IPAddr
	if err := json.Unmarshal(bs, &ip2); err != nil {
		fmt.Fprintln(os.Stderr, "unmarshal:", err)
		return
	}
	bs2, _ := json.Marshal(ip2)
	fmt.Printf("\nround-trip JSON 127.0.0.1: first=%s  second=%s  equal=%v\n",
		string(bs), string(bs2), string(bs) == string(bs2))

	// Construct from a /32 explicitly: same Display?
	ip32, _ := types.ParseIPAddr("127.0.0.1/32")
	bs32, _ := ip32.MarshalJSON()
	fmt.Printf("ip32 String=%q  MarshalJSON=%s\n", ip32.String(), string(bs32))
}
