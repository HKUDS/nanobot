package types

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/hexops/autogold/v2"
)

func TestUIAction_Intent_Marshal(t *testing.T) {
	action := UIAction{
		Type: "intent",
		Intent: &UIIntent{
			Intent: "test-intent",
			Params: map[string]any{
				"param1": "value1",
				"param2": 123,
			},
		},
	}

	data, err := json.Marshal(action)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction with intent: %v", err)
	}

	autogold.Expect(`{"payload":{"intent":"test-intent","params":{"param1":"value1","param2":123}},"type":"intent"}`).Equal(t, string(data))
}

func TestUIAction_Tool_Marshal(t *testing.T) {
	action := UIAction{
		Type: "tool",
		Tool: &UITool{
			ToolName: "test-tool",
			Params: map[string]any{
				"input": "test-input",
				"count": 456,
			},
		},
	}

	data, err := json.Marshal(action)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction with tool: %v", err)
	}

	autogold.Expect(`{"payload":{"toolName":"test-tool","params":{"count":456,"input":"test-input"}},"type":"tool"}`).Equal(t, string(data))
}

func TestUIAction_Prompt_Marshal(t *testing.T) {
	action := UIAction{
		Type: "prompt",
		Prompt: &UIPrompt{
			Prompt: "What is the weather like?",
		},
	}

	data, err := json.Marshal(action)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction with prompt: %v", err)
	}

	autogold.Expect(`{"payload":{"prompt":"What is the weather like?","params":null},"type":"prompt"}`).Equal(t, string(data))
}

func TestUIAction_Empty_Marshal(t *testing.T) {
	action := UIAction{
		Type: "unknown",
	}

	data, err := json.Marshal(action)
	if err != nil {
		t.Fatalf("Failed to marshal empty UIAction: %v", err)
	}

	autogold.Expect(`{}`).Equal(t, string(data))
}

func TestUIAction_Intent_Unmarshal(t *testing.T) {
	jsonData := `{"type":"intent","payload":{"intent":"test-intent","params":{"param1":"value1","param2":123}}}`

	var action UIAction
	err := json.Unmarshal([]byte(jsonData), &action)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction with intent: %v", err)
	}

	expected := UIAction{
		Type: "intent",
		Intent: &UIIntent{
			Intent: "test-intent",
			Params: map[string]any{
				"param1": "value1",
				"param2": float64(123), // JSON unmarshaling converts numbers to float64
			},
		},
	}

	if !reflect.DeepEqual(action, expected) {
		t.Errorf("Expected %+v, got %+v", expected, action)
	}
}

func TestUIAction_Tool_Unmarshal(t *testing.T) {
	jsonData := `{"type":"tool","payload":{"toolName":"test-tool","params":{"input":"test-input","count":456}}}`

	var action UIAction
	err := json.Unmarshal([]byte(jsonData), &action)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction with tool: %v", err)
	}

	expected := UIAction{
		Type: "tool",
		Tool: &UITool{
			ToolName: "test-tool",
			Params: map[string]any{
				"input": "test-input",
				"count": float64(456), // JSON unmarshaling converts numbers to float64
			},
		},
	}

	if !reflect.DeepEqual(action, expected) {
		t.Errorf("Expected %+v, got %+v", expected, action)
	}
}

func TestUIAction_Prompt_Unmarshal(t *testing.T) {
	jsonData := `{"type":"prompt","payload":{"prompt":"What is the weather like?"}}`

	var action UIAction
	err := json.Unmarshal([]byte(jsonData), &action)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction with prompt: %v", err)
	}

	expected := UIAction{
		Type: "prompt",
		Prompt: &UIPrompt{
			Prompt: "What is the weather like?",
		},
	}

	if !reflect.DeepEqual(action, expected) {
		t.Errorf("Expected %+v, got %+v", expected, action)
	}
}

func TestUIAction_UnknownType_Unmarshal(t *testing.T) {
	jsonData := `{"type":"unknown","payload":{"something":"value"}}`

	var action UIAction
	err := json.Unmarshal([]byte(jsonData), &action)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction with unknown type: %v", err)
	}

	expected := UIAction{
		Type: "unknown",
	}

	if !reflect.DeepEqual(action, expected) {
		t.Errorf("Expected %+v, got %+v", expected, action)
	}
}

func TestUIAction_RoundTrip_Intent(t *testing.T) {
	original := UIAction{
		Type: "intent",
		Intent: &UIIntent{
			Intent: "round-trip-intent",
			Params: map[string]any{
				"key": "value",
				"num": 789,
			},
		},
	}

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction: %v", err)
	}

	var unmarshalled UIAction
	err = json.Unmarshal(data, &unmarshalled)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction: %v", err)
	}

	// Adjust for float64 conversion in JSON unmarshaling
	expected := original
	expected.Intent.Params["num"] = float64(789)

	if !reflect.DeepEqual(unmarshalled, expected) {
		t.Errorf("Round trip failed. Expected %+v, got %+v", expected, unmarshalled)
	}
}

func TestUIAction_RoundTrip_Tool(t *testing.T) {
	original := UIAction{
		Type: "tool",
		Tool: &UITool{
			ToolName: "round-trip-tool",
			Params: map[string]any{
				"setting": "enabled",
				"timeout": 30,
			},
		},
	}

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction: %v", err)
	}

	var unmarshalled UIAction
	err = json.Unmarshal(data, &unmarshalled)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction: %v", err)
	}

	// Adjust for float64 conversion in JSON unmarshaling
	expected := original
	expected.Tool.Params["timeout"] = float64(30)

	if !reflect.DeepEqual(unmarshalled, expected) {
		t.Errorf("Round trip failed. Expected %+v, got %+v", expected, unmarshalled)
	}
}

func TestUIAction_RoundTrip_Prompt(t *testing.T) {
	original := UIAction{
		Type: "prompt",
		Prompt: &UIPrompt{
			Prompt: "Round trip test prompt",
		},
	}

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal UIAction: %v", err)
	}

	var unmarshalled UIAction
	err = json.Unmarshal(data, &unmarshalled)
	if err != nil {
		t.Fatalf("Failed to unmarshal UIAction: %v", err)
	}

	if !reflect.DeepEqual(unmarshalled, original) {
		t.Errorf("Round trip failed. Expected %+v, got %+v", original, unmarshalled)
	}
}

func TestUIPrompt_EmptyPrompt(t *testing.T) {
	prompt := UIPrompt{
		Prompt: "",
	}

	data, err := json.Marshal(prompt)
	if err != nil {
		t.Fatalf("Failed to marshal empty UIPrompt: %v", err)
	}

	autogold.Expect(`{"params":null}`).Equal(t, string(data))
}

func TestUIAction_InvalidJSON_Unmarshal(t *testing.T) {
	invalidJSON := `{"type":"intent","payload":invalid}`

	var action UIAction
	err := json.Unmarshal([]byte(invalidJSON), &action)
	if err == nil {
		t.Fatal("Expected error when unmarshaling invalid JSON, but got nil")
	}
}
