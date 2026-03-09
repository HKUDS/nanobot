package types

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

var (
	MetaPrefix          = "ai.nanobot.meta/"
	ToolCallConfirmType = "toolcall/confirm"

	AsyncMetaKey = "ai.nanobot.async"
)

type ToolCallConfirm struct {
	Type       string    `json:"type"`
	MCPServer  string    `json:"mcpServer,omitempty"`
	Tool       mcp.Tool  `json:"tool,omitempty"`
	Invocation *ToolCall `json:"invocation,omitempty"`
}

func (t ToolCallConfirm) Message() string {
	return fmt.Sprintf("Allow call to tool?\nTool: %s\nDescription: %s\nArgs: %s", t.Tool.Name,
		t.Tool.Description, t.Invocation.Arguments)
}

func (t ToolCallConfirm) MarshalJSON() ([]byte, error) {
	type Alias ToolCallConfirm
	if t.Type == "" {
		t.Type = ToolCallConfirmType
	}
	return MarshalMeta((Alias)(t))
}

func (t *ToolCallConfirm) UnmarshalJSON(data []byte) error {
	type Alias ToolCallConfirm
	if err := UnmarshalMeta(data, (*Alias)(t)); err != nil {
		return err
	}
	t.Type = ToolCallConfirmType
	return nil
}

func UnmarshalMeta[T any](data []byte, out *T) error {
	var (
		raw    map[string]any
		result = make(map[string]any)
	)
	if err := mcp.JSONCoerce(data, &raw); err != nil {
		return err
	}

	for k, v := range raw {
		if k == "progressToken" {
			result[k] = v
		}
		switch str := v.(type) {
		case string:
			if len(str) > 0 {
				if str[0] == '{' || str[0] == '[' {
					var obj any
					if err := json.Unmarshal([]byte(str), &obj); err != nil {
						return fmt.Errorf("invalid JSON for %s: %w", k, err)
					}
					v = obj
				}
			}
		default:
			return fmt.Errorf("invalid value for %s, only string allow: %v", k, v)
		}
		result[strings.TrimPrefix(k, MetaPrefix)] = v
	}

	return mcp.JSONCoerce(result, out)
}

func MarshalMeta(obj any) ([]byte, error) {
	data := map[string]any{}
	if err := mcp.JSONCoerce(obj, &data); err != nil {
		return nil, err
	}
	for k, v := range data {
		if k == "progressToken" {
			continue
		}
		if v == nil {
			// drop nulls, not allowed
			continue
		}
		var toString string
		switch v := v.(type) {
		case string:
			toString = v
		default:
			if err := mcp.JSONCoerce(v, &toString); err != nil {
				return nil, err
			}
			if toString == "null" {
				delete(data, k)
				continue
			}
			if toString[0] != '[' && toString[0] != '{' {
				return nil, fmt.Errorf("invalid value for %s, only string, array, or objects allowed: %s", k, toString)
			}
		}

		if !strings.HasPrefix(k, MetaPrefix) {
			delete(data, k)
			k = MetaPrefix + k
		}
		data[k] = toString
	}
	return json.Marshal(data)
}

func Meta(m map[string]any) map[string]any {
	if m == nil {
		return nil
	}
	return map[string]any{MetaNanobot: m}
}

func IsModelTool(t mcp.Tool) bool {
	uiAttr, _ := t.Meta["ui"].(map[string]any)
	visibility, _ := uiAttr["visibility"].([]string)
	return len(visibility) == 0 || slices.Contains(visibility, "model")
}

func IsUITool(t mcp.Tool) bool {
	uiAttr, _ := t.Meta["ui"].(map[string]any)
	visibility, _ := uiAttr["visibility"].([]string)
	return len(visibility) == 0 || slices.Contains(visibility, "app")
}
