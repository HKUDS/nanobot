package anthropic

import (
	"encoding/json"
)

type Request struct {
	MaxTokens     int            `json:"max_tokens"`
	Messages      []Message      `json:"messages"`
	Model         string         `json:"model"`
	StopSequences []string       `json:"stop_sequences,omitempty"`
	Stream        bool           `json:"stream,omitempty"`
	System        string         `json:"system,omitempty"`
	Temperature   *json.Number   `json:"temperature,omitempty"`
	ToolChoice    *ToolChoice    `json:"tool_choice,omitempty"`
	Tools         []CustomTool   `json:"tools,omitempty"`
	TopP          *json.Number   `json:"top_p,omitempty"`
	Metadata      map[string]any `json:"metadata,omitempty"`
}

type Response struct {
	ID           string    `json:"id"`
	Model        string    `json:"model"`
	Content      []Content `json:"content"`
	Role         string    `json:"role"`
	StopReason   *string   `json:"stop_reason"`
	StopSequence *string   `json:"stop_sequence"`
	Usage        *Usage    `json:"usage"`
}

type Usage struct {
	CacheCreationInputTokens *int           `json:"cache_creation_input_tokens"`
	CacheReadInputTokens     *int           `json:"cache_read_input_tokens"`
	InputTokens              *int           `json:"input_tokens"`
	OutputTokens             *int           `json:"output_tokens"`
	ServerToolUse            *ServerToolUse `json:"server_tool_use"`
}

type ServerToolUse struct {
	WebSearchRequests int `json:"web_search_requests"`
}

type ToolChoice struct {
	// Type is either "auto", "tool", or "none"
	Type                   string
	DisableParallelToolUse bool   `json:"disable_parallel_tool_use,omitempty"`
	Name                   string `json:"name,omitempty"`
}

type Message struct {
	Content []Content `json:"content"`
	Role    string    `json:"role"`
}

type Content struct {
	Type string `json:"type"`

	// Type = text
	Text *string `json:"text,omitempty"`

	// Type = image
	Source ContentSource `json:"source,omitzero"`

	// Type = tool_use
	ID    string         `json:"id,omitempty"`
	Input map[string]any `json:"input,omitzero"`
	Name  string         `json:"name,omitempty"`

	// Type = tool_result
	ToolUseID string    `json:"tool_use_id,omitempty"`
	Content   []Content `json:"content,omitempty"`
	IsError   bool      `json:"is_error,omitempty"`
}

type ContentSource struct {
	Type string `json:"type"`

	// Type = base64
	Data      string `json:"data,omitempty"`
	MediaType string `json:"media_type,omitempty"`

	// Type = url
	URL string `json:"url,omitempty"`
}

type CustomTool struct {
	Type        string          `json:"type,omitempty"`
	Name        string          `json:"name,omitempty"`
	InputSchema json.RawMessage `json:"input_schema,omitzero"`
	Description string          `json:"description,omitempty"`
	Attributes  map[string]any  `json:"-"`
}

func (c *CustomTool) UnmarshalJSON(data []byte) error {
	type Alias CustomTool
	if err := json.Unmarshal(data, (*Alias)(c)); err != nil {
		return err
	}

	c.Attributes = make(map[string]any)
	if err := json.Unmarshal(data, &c.Attributes); err != nil {
		return err
	}

	delete(c.Attributes, "name")
	delete(c.Attributes, "input_schema")
	delete(c.Attributes, "strict")
	delete(c.Attributes, "description")
	c.Type = ""

	return nil
}

func (c CustomTool) MarshalJSON() ([]byte, error) {
	if c.Type == "" {
		c.Type = "custom"
	}

	type Alias CustomTool
	data, err := json.Marshal((Alias)(c))
	if err != nil {
		return nil, err
	}

	if len(c.Attributes) > 0 {
		base := map[string]any{}
		if err := json.Unmarshal(data, &base); err != nil {
			return nil, err
		}
		var toRemove []string
		if c.Attributes["type"] != "" && c.Attributes["type"] != "custom" {
			toRemove = append(toRemove, "description", "input_schema")
		}
		for k, v := range c.Attributes {
			if l, ok := v.([]any); k == "remove" && ok {
				for _, v := range l {
					if s, ok := v.(string); ok {
						toRemove = append(toRemove, s)
					}
				}
				continue
			}
			if v != "" {
				base[k] = v
			}
		}
		for _, k := range toRemove {
			delete(base, k)
		}
		return json.Marshal(base)
	}

	return data, nil
}

type DeltaEvent struct {
	Type         string   `json:"type"`
	Index        int      `json:"index"`
	Message      Response `json:"message"`
	ContentBlock Content  `json:"content_block"`
	Delta        Delta    `json:"delta"`
}

type Delta struct {
	Type        string `json:"type"`
	Text        string `json:"text,omitempty"`
	PartialJSON string `json:"partial_json,omitempty"`
}
