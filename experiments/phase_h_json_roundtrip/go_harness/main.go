// roundtrip harness; JSON policy → Cedar text → JSON policy
//
// stdin:  one JSON object per line: {"id": "...", "policy_json": {...}}
// stdout: one JSON result per line
//
// Result fields:
//   id        ; probe identifier passed in
//   outcome   ; "panic" | "parse_fail" | "clean" | "silent_diff"
//   stage     ; stage at which outcome occurred
//   detail    ; human-readable detail string
//   cedar_text; Cedar text produced (if marshal_cedar succeeded)
//   out_json  ; final JSON produced (if full round-trip succeeded)
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"runtime/debug"

	cedar "github.com/cedar-policy/cedar-go"
)

type ProbeInput struct {
	ID         string          `json:"id"`
	PolicyJSON json.RawMessage `json:"policy_json"`
}

type ProbeResult struct {
	ID        string `json:"id"`
	Outcome   string `json:"outcome"`
	Stage     string `json:"stage"`
	Detail    string `json:"detail"`
	CedarText string `json:"cedar_text,omitempty"`
	OutJSON   string `json:"out_json,omitempty"`
}

func runRoundtrip(input ProbeInput) (res ProbeResult) {
	res.ID = input.ID

	// Recover from panics; these are the NEW-2 class findings
	defer func() {
		if r := recover(); r != nil {
			res.Outcome = "panic"
			res.Detail = fmt.Sprintf("panic: %v\nstack:\n%s", r, debug.Stack())
		}
	}()

	// Stage 1: JSON → Policy AST
	var p cedar.Policy
	if err := p.UnmarshalJSON([]byte(input.PolicyJSON)); err != nil {
		res.Outcome = "parse_fail"
		res.Stage = "json_unmarshal"
		res.Detail = err.Error()
		return
	}

	// Stage 2: Policy AST → Cedar text
	cedarBytes := p.MarshalCedar()
	cedarText := string(cedarBytes)
	res.CedarText = cedarText
	res.Stage = "marshal_cedar"

	// Stage 3: Cedar text → Policy AST (second parse)
	var p2 cedar.Policy
	if err := p2.UnmarshalCedar(cedarBytes); err != nil {
		res.Outcome = "parse_fail"
		res.Stage = "cedar_unmarshal"
		res.Detail = fmt.Sprintf("cedar text: %q  error: %v", cedarText, err)
		return
	}

	// Stage 4: Policy AST → JSON (round-tripped)
	outJSON, err := p2.MarshalJSON()
	if err != nil {
		res.Outcome = "parse_fail"
		res.Stage = "json_marshal"
		res.Detail = err.Error()
		return
	}
	res.OutJSON = string(outJSON)

	// Stage 5: Compare original JSON vs round-tripped JSON
	// Normalize both through interface{} for canonical comparison
	inputNorm, err1 := normalizeJSON([]byte(input.PolicyJSON))
	outputNorm, err2 := normalizeJSON(outJSON)
	if err1 != nil || err2 != nil {
		res.Outcome = "parse_fail"
		res.Stage = "compare"
		res.Detail = fmt.Sprintf("normalize error: %v / %v", err1, err2)
		return
	}

	if inputNorm == outputNorm {
		res.Outcome = "clean"
		res.Stage = "compare"
		res.Detail = "round-trip identity holds"
	} else {
		res.Outcome = "silent_diff"
		res.Stage = "compare"
		res.Detail = fmt.Sprintf("INPUT:  %s\nOUTPUT: %s", inputNorm, outputNorm)
	}
	return
}

// normalizeJSON produces a canonical JSON string for comparison
func normalizeJSON(b []byte) (string, error) {
	var v interface{}
	if err := json.Unmarshal(b, &v); err != nil {
		return "", err
	}
	out, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	return string(out), nil
}

func main() {
	enc := json.NewEncoder(os.Stdout)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024*1024), 64*1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var input ProbeInput
		if err := json.Unmarshal(line, &input); err != nil {
			enc.Encode(ProbeResult{
				ID:      "?",
				Outcome: "parse_fail",
				Stage:   "harness_input",
				Detail:  err.Error(),
			})
			continue
		}
		res := runRoundtrip(input)
		enc.Encode(res)
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, "scanner error:", err)
		os.Exit(1)
	}
}
