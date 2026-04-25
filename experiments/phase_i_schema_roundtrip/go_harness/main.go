// Schema-roundtrip probe for cedar-go x/exp/schema.
//
// Reads a JSON schema, performs UnmarshalJSON -> MarshalCedar ->
// UnmarshalCedar -> MarshalJSON. Emits a JSON object on stdout summarising
// the outcome at each stage plus the final-vs-original JSON shape diff.
//
// Output object keys (always present):
//   stage          : "unmarshal_json" | "marshal_cedar" | "unmarshal_cedar"
//                  | "marshal_json"   | "ok"
//   classification : "clean" | "silent_diff" | "parse_fail" | "panic"
//   error          : string | null
//   marshalled_cedar : string | null
//   roundtripped_json : string | null      // re-marshalled JSON
//   diff_summary     : string | null       // human-readable summary of
//                                          // diffs vs original JSON
//
// Exit code is always 0 on a clean classification (so the Python
// wrapper can read the JSON unconditionally). A nonzero exit only means
// the harness itself crashed.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"sort"
	"strings"

	"github.com/cedar-policy/cedar-go/x/exp/schema"
)

type result struct {
	Stage            string  `json:"stage"`
	Classification   string  `json:"classification"`
	Error            *string `json:"error"`
	MarshalledCedar  *string `json:"marshalled_cedar"`
	RoundtrippedJSON *string `json:"roundtripped_json"`
	DiffSummary      *string `json:"diff_summary"`
}

func sptr(s string) *string { return &s }

func emit(r result) {
	b, _ := json.Marshal(r)
	fmt.Println(string(b))
}

// canonicaliseJSON reads a JSON byte string and returns a canonical
// recursive map[string]any representation, with map keys sorted via
// json.Marshal's deterministic ordering. Used for structural equality
// only -- not preserving JSON-numeric formatting.
func canonicaliseJSON(b []byte) (any, error) {
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return nil, err
	}
	return v, nil
}

// summariseDiff returns a short human-readable description of where the
// two JSON trees differ. Truncates at 4 sample paths.
func summariseDiff(a, b any) string {
	var diffs []string
	var walk func(path string, x, y any)
	walk = func(path string, x, y any) {
		if len(diffs) >= 4 {
			return
		}
		switch xv := x.(type) {
		case map[string]any:
			yv, ok := y.(map[string]any)
			if !ok {
				diffs = append(diffs, fmt.Sprintf("%s: type mismatch (%T vs %T)", path, x, y))
				return
			}
			keys := map[string]struct{}{}
			for k := range xv {
				keys[k] = struct{}{}
			}
			for k := range yv {
				keys[k] = struct{}{}
			}
			ks := make([]string, 0, len(keys))
			for k := range keys {
				ks = append(ks, k)
			}
			sort.Strings(ks)
			for _, k := range ks {
				xv2, xok := xv[k]
				yv2, yok := yv[k]
				switch {
				case xok && !yok:
					diffs = append(diffs, fmt.Sprintf("%s.%s: dropped", path, k))
				case !xok && yok:
					diffs = append(diffs, fmt.Sprintf("%s.%s: added", path, k))
				default:
					walk(path+"."+k, xv2, yv2)
				}
				if len(diffs) >= 4 {
					return
				}
			}
		case []any:
			yv, ok := y.([]any)
			if !ok {
				diffs = append(diffs, fmt.Sprintf("%s: type mismatch (%T vs %T)", path, x, y))
				return
			}
			if len(xv) != len(yv) {
				diffs = append(diffs, fmt.Sprintf("%s: length %d vs %d", path, len(xv), len(yv)))
				return
			}
			for i := range xv {
				walk(fmt.Sprintf("%s[%d]", path, i), xv[i], yv[i])
				if len(diffs) >= 4 {
					return
				}
			}
		default:
			if !reflect.DeepEqual(x, y) {
				diffs = append(diffs, fmt.Sprintf("%s: %v -> %v", path, x, y))
			}
		}
	}
	walk("$", a, b)
	if len(diffs) == 0 {
		return ""
	}
	return strings.Join(diffs, "; ")
}

func main() {
	defer func() {
		if r := recover(); r != nil {
			msg := fmt.Sprintf("panic: %v", r)
			emit(result{
				Stage:          "panic",
				Classification: "panic",
				Error:          &msg,
			})
			os.Exit(0)
		}
	}()

	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: probe <json-path>")
		os.Exit(2)
	}
	jsonBytes, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		os.Exit(2)
	}

	var s schema.Schema
	if err := s.UnmarshalJSON(jsonBytes); err != nil {
		msg := err.Error()
		emit(result{
			Stage:          "unmarshal_json",
			Classification: "parse_fail",
			Error:          &msg,
		})
		return
	}

	cedarBytes, err := s.MarshalCedar()
	if err != nil {
		msg := err.Error()
		emit(result{
			Stage:          "marshal_cedar",
			Classification: "parse_fail",
			Error:          &msg,
		})
		return
	}
	cedarStr := string(cedarBytes)

	var s2 schema.Schema
	if err := s2.UnmarshalCedar(cedarBytes); err != nil {
		msg := err.Error()
		emit(result{
			Stage:           "unmarshal_cedar",
			Classification:  "parse_fail",
			Error:           &msg,
			MarshalledCedar: &cedarStr,
		})
		return
	}

	jsonOut, err := s2.MarshalJSON()
	if err != nil {
		msg := err.Error()
		emit(result{
			Stage:           "marshal_json",
			Classification:  "parse_fail",
			Error:           &msg,
			MarshalledCedar: &cedarStr,
		})
		return
	}
	jsonOutStr := string(jsonOut)

	origCanon, err := canonicaliseJSON(jsonBytes)
	if err != nil {
		msg := "canonicalise input: " + err.Error()
		emit(result{
			Stage:            "marshal_json",
			Classification:   "parse_fail",
			Error:            &msg,
			MarshalledCedar:  &cedarStr,
			RoundtrippedJSON: &jsonOutStr,
		})
		return
	}
	rtCanon, err := canonicaliseJSON(jsonOut)
	if err != nil {
		msg := "canonicalise rt: " + err.Error()
		emit(result{
			Stage:            "marshal_json",
			Classification:   "parse_fail",
			Error:            &msg,
			MarshalledCedar:  &cedarStr,
			RoundtrippedJSON: &jsonOutStr,
		})
		return
	}

	if reflect.DeepEqual(origCanon, rtCanon) {
		emit(result{
			Stage:            "ok",
			Classification:   "clean",
			MarshalledCedar:  &cedarStr,
			RoundtrippedJSON: &jsonOutStr,
		})
		return
	}

	summary := summariseDiff(origCanon, rtCanon)
	emit(result{
		Stage:            "ok",
		Classification:   "silent_diff",
		MarshalledCedar:  &cedarStr,
		RoundtrippedJSON: &jsonOutStr,
		DiffSummary:      sptr(summary),
	})
}
