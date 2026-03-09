package types

import (
	"encoding/json"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

type UIAction struct {
	Type   string
	Intent *UIIntent
	Tool   *UITool
	Prompt *UIPrompt
}

func (u *UIAction) UnmarshalJSON(data []byte) error {
	var temp struct {
		Type string `json:"type"`
	}

	if err := json.Unmarshal(data, &temp); err != nil {
		return err
	}

	u.Type = temp.Type
	switch u.Type {
	case "intent":
		u.Intent = &UIIntent{}
		return json.Unmarshal(data, &struct {
			Payload *UIIntent `json:"payload"`
		}{
			Payload: u.Intent,
		})
	case "tool":
		u.Tool = &UITool{}
		return json.Unmarshal(data, &struct {
			Payload *UITool `json:"payload"`
		}{
			Payload: u.Tool,
		})
	case "prompt":
		u.Prompt = &UIPrompt{}
		return json.Unmarshal(data, &struct {
			Payload *UIPrompt `json:"payload"`
		}{
			Payload: u.Prompt,
		})
	}
	return nil
}

func (u UIAction) MarshalJSON() ([]byte, error) {
	if u.Intent != nil {
		return json.Marshal(map[string]any{
			"type":    "intent",
			"payload": u.Intent,
		})
	} else if u.Tool != nil {
		return json.Marshal(map[string]any{
			"type":    "tool",
			"payload": u.Tool,
		})
	} else if u.Prompt != nil {
		return json.Marshal(map[string]any{
			"type":    "prompt",
			"payload": u.Prompt,
		})
	}
	return []byte("{}"), nil
}

type UIIntent struct {
	Intent string         `json:"intent"`
	Params map[string]any `json:"params"`
}

type UIPrompt struct {
	Prompt           string              `json:"prompt,omitempty"`
	PromptName       string              `json:"promptName,omitempty"`
	Params           map[string]string   `json:"params"`
	RenderedMessages []mcp.PromptMessage `json:"renderedMessages,omitempty"`
}

type UITool struct {
	ToolName string         `json:"toolName"`
	Params   map[string]any `json:"params"`
}
