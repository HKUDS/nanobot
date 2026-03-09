package completions

import (
	"encoding/json"
)

type Request struct {
	Messages            []Message       `json:"messages"`
	Model               string          `json:"model"`
	MaxTokens           *int            `json:"max_tokens,omitempty"`
	MaxCompletionTokens *int            `json:"max_completion_tokens,omitempty"`
	Temperature         *json.Number    `json:"temperature,omitempty"`
	TopP                *json.Number    `json:"top_p,omitempty"`
	Stream              bool            `json:"stream,omitempty"`
	StreamOptions       *StreamOptions  `json:"stream_options,omitempty"`
	Stop                []string        `json:"stop,omitempty"`
	ToolChoice          *ToolChoice     `json:"tool_choice,omitempty"`
	Tools               []Tool          `json:"tools,omitempty"`
	User                string          `json:"user,omitempty"`
	Metadata            map[string]any  `json:"metadata,omitempty"`
	ResponseFormat      *ResponseFormat `json:"response_format,omitempty"`
}

type StreamOptions struct {
	IncludeUsage bool `json:"include_usage,omitempty"`
}

type Message struct {
	Role       string         `json:"role"`
	Content    MessageContent `json:"content,omitempty"`
	Reasoning  *string        `json:"reasoning,omitempty"`
	Name       string         `json:"name,omitempty"`
	ToolCalls  []ToolCall     `json:"tool_calls,omitempty"`
	ToolCallID string         `json:"tool_call_id,omitempty"`
	Refusal    *string        `json:"refusal,omitempty"`
}

type MessageContent struct {
	Text         *string       `json:"-"`
	ContentParts []ContentPart `json:",inline"`
}

func (m MessageContent) MarshalJSON() ([]byte, error) {
	if m.Text != nil {
		return json.Marshal(*m.Text)
	}
	if m.ContentParts != nil {
		return json.Marshal(m.ContentParts)
	}
	return []byte("null"), nil
}

func (m *MessageContent) UnmarshalJSON(data []byte) error {
	if data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		m.Text = &s
		return nil
	}
	m.ContentParts = make([]ContentPart, 0)
	return json.Unmarshal(data, &m.ContentParts)
}

type ContentPart struct {
	Type     string    `json:"type"`
	Text     string    `json:"text,omitempty"`
	ImageURL *ImageURL `json:"image_url,omitempty"`
}

type ImageURL struct {
	URL    string `json:"url"`
	Detail string `json:"detail,omitempty"`
}

type Tool struct {
	Type     string   `json:"type"`
	Function Function `json:"function"`
}

type Function struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
	Strict      *bool           `json:"strict,omitempty"`
}

type ToolChoice struct {
	Type     string          `json:"type,omitempty"`
	Function *ToolChoiceFunc `json:"function,omitempty"`
}

type ToolChoiceFunc struct {
	Name string `json:"name"`
}

func (t ToolChoice) MarshalJSON() ([]byte, error) {
	if t.Type == "function" && t.Function != nil {
		return json.Marshal(struct {
			Type     string          `json:"type"`
			Function *ToolChoiceFunc `json:"function"`
		}{
			Type:     t.Type,
			Function: t.Function,
		})
	}
	return json.Marshal(t.Type)
}

func (t *ToolChoice) UnmarshalJSON(data []byte) error {
	if data[0] == '"' {
		return json.Unmarshal(data, &t.Type)
	}

	var obj struct {
		Type     string          `json:"type"`
		Function *ToolChoiceFunc `json:"function"`
	}
	if err := json.Unmarshal(data, &obj); err != nil {
		return err
	}

	t.Type = obj.Type
	t.Function = obj.Function
	return nil
}

type ResponseFormat struct {
	Type       string      `json:"type"`
	JSONSchema *JSONSchema `json:"json_schema,omitempty"`
}

type JSONSchema struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Schema      json.RawMessage `json:"schema"`
	Strict      bool            `json:"strict,omitempty"`
}

type Response struct {
	ID                string   `json:"id"`
	Object            string   `json:"object"`
	Created           int64    `json:"created"`
	Model             string   `json:"model"`
	Choices           []Choice `json:"choices"`
	Usage             *Usage   `json:"usage,omitempty"`
	SystemFingerprint *string  `json:"system_fingerprint,omitempty"`
}

type Choice struct {
	Index        int          `json:"index"`
	Message      *Message     `json:"message,omitempty"`
	Delta        *ChoiceDelta `json:"delta,omitempty"`
	FinishReason *string      `json:"finish_reason,omitempty"`
	Logprobs     *Logprobs    `json:"logprobs,omitempty"`
}

type ChoiceDelta struct {
	Role      string     `json:"role,omitempty"`
	Content   *string    `json:"content,omitempty"`
	Reasoning *string    `json:"reasoning,omitempty"`
	ToolCalls []ToolCall `json:"tool_calls,omitempty"`
	Refusal   *string    `json:"refusal,omitempty"`
}

type ToolCall struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"`
	Function FunctionCall `json:"function"`
	Index    *int         `json:"index,omitempty"`
}

type FunctionCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type Usage struct {
	PromptTokens            int                      `json:"prompt_tokens"`
	CompletionTokens        int                      `json:"completion_tokens"`
	TotalTokens             int                      `json:"total_tokens"`
	PromptTokensDetails     *PromptTokensDetails     `json:"prompt_tokens_details,omitempty"`
	CompletionTokensDetails *CompletionTokensDetails `json:"completion_tokens_details,omitempty"`
}

type PromptTokensDetails struct {
	CachedTokens int `json:"cached_tokens,omitempty"`
}

type CompletionTokensDetails struct {
	ReasoningTokens int `json:"reasoning_tokens,omitempty"`
}

type Logprobs struct {
	Content []TokenLogprob `json:"content"`
}

type TokenLogprob struct {
	Token       string       `json:"token"`
	Logprob     float64      `json:"logprob"`
	Bytes       []int        `json:"bytes,omitempty"`
	TopLogprobs []TopLogprob `json:"top_logprobs"`
}

type TopLogprob struct {
	Token   string  `json:"token"`
	Logprob float64 `json:"logprob"`
	Bytes   []int   `json:"bytes,omitempty"`
}

// StreamChunk represents a streaming response chunk
type StreamChunk struct {
	ID                string   `json:"id"`
	Object            string   `json:"object"`
	Created           int64    `json:"created"`
	Model             string   `json:"model"`
	Choices           []Choice `json:"choices"`
	Usage             *Usage   `json:"usage,omitempty"`
	SystemFingerprint *string  `json:"system_fingerprint,omitempty"`
}

// ErrorResponse represents an error from the API
type ErrorResponse struct {
	Error ErrorDetail `json:"error"`
}

type ErrorDetail struct {
	Message string  `json:"message"`
	Type    string  `json:"type"`
	Param   *string `json:"param,omitempty"`
	Code    *string `json:"code,omitempty"`
}
