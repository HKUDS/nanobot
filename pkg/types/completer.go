package types

import (
	"context"
	"encoding/json"
	"slices"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

type Completer interface {
	Complete(ctx context.Context, req CompletionRequest, opts ...CompletionOptions) (*CompletionResponse, error)
}

type CompletionOptions struct {
	ProgressToken      any
	Chat               *bool
	ToolChoice         *mcp.ToolChoice
	Tools              []mcp.Tool
	ToolIncludeContext string
	ToolSource         string
}

func (c CompletionOptions) Merge(other CompletionOptions) (result CompletionOptions) {
	result.ProgressToken = complete.Last(c.ProgressToken, other.ProgressToken)
	result.Chat = complete.Last(c.Chat, other.Chat)
	result.ToolChoice = complete.Last(c.ToolChoice, other.ToolChoice)
	result.Tools = append(c.Tools, other.Tools...)
	result.ToolIncludeContext = complete.Last(c.ToolIncludeContext, other.ToolIncludeContext)
	result.ToolSource = complete.Last(c.ToolSource, other.ToolSource)
	return
}

type CompletionRequest struct {
	Model            string               `json:"model,omitempty"`
	Agent            string               `json:"agent,omitempty"`
	ThreadName       string               `json:"threadName,omitempty"`
	NewThread        bool                 `json:"newThread,omitempty"`
	Input            []Message            `json:"input,omitzero"`
	ModelPreferences mcp.ModelPreferences `json:"modelPreferences,omitzero"`
	SystemPrompt     string               `json:"systemPrompt,omitzero"`
	MaxTokens        int                  `json:"maxTokens,omitempty"`
	ToolChoice       string               `json:"toolChoice,omitempty"`
	OutputSchema     *OutputSchema        `json:"outputSchema,omitempty"`
	Temperature      *json.Number         `json:"temperature,omitempty"`
	Truncation       string               `json:"truncation,omitempty"`
	TopP             *json.Number         `json:"topP,omitempty"`
	Metadata         map[string]any       `json:"metadata,omitempty"`
	Tools            []ToolUseDefinition  `json:"tools,omitzero"`
	Reasoning        *AgentReasoning      `json:"reasoning,omitempty"`
}

func (r CompletionRequest) GetAgent() string {
	if r.Agent != "" {
		return r.Agent
	}
	return r.Model
}

func (r CompletionRequest) Reset() CompletionRequest {
	r.Input = nil
	r.NewThread = false
	return r
}

type ToolUseDefinition struct {
	Name        string          `json:"name,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
	Description string          `json:"description,omitempty"`
	Attributes  map[string]any  `json:"-"`
}

type CompletionProgress struct {
	Model     string         `json:"model,omitempty"`
	Agent     string         `json:"agent,omitempty"`
	MessageID string         `json:"messageID,omitempty"`
	Role      string         `json:"role,omitempty"`
	Item      CompletionItem `json:"item,omitempty"`
}

const CompletionProgressMetaKey = "ai.nanobot.progress/completion"

type Message struct {
	ID      string           `json:"id,omitempty"`
	Created *time.Time       `json:"created,omitempty"`
	Role    string           `json:"role,omitempty"`
	Items   []CompletionItem `json:"items,omitempty"`
	HasMore bool             `json:"hasMore,omitempty"`
}

type CompletionItem struct {
	ID             string          `json:"id,omitempty"`
	Partial        bool            `json:"partial,omitempty"`
	HasMore        bool            `json:"hasMore,omitempty"`
	Content        *mcp.Content    `json:"content,omitempty"`
	ToolCall       *ToolCall       `json:"toolCall,omitempty"`
	ToolCallResult *ToolCallResult `json:"toolCallResult,omitempty"`
	Reasoning      *Reasoning      `json:"reasoning,omitempty"`
}

func (c *CompletionItem) UnmarshalJSON(data []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	c.ID = ""
	if id, ok := raw["id"]; ok {
		if err := json.Unmarshal(id, &c.ID); err != nil {
			return err
		}
	}

	if hasMore, ok := raw["hasMore"]; ok {
		if err := json.Unmarshal(hasMore, &c.HasMore); err != nil {
			return err
		}
	}

	if partial, ok := raw["partial"]; ok {
		if err := json.Unmarshal(partial, &c.Partial); err != nil {
			return err
		}
	}

	var typeField string
	if t, ok := raw["type"]; ok {
		if err := json.Unmarshal(t, &typeField); err != nil {
			return err
		}
	}

	switch typeField {
	case "text", "image", "audio", "resource", "resource_link":
		c.Content = &mcp.Content{}
		if err := json.Unmarshal(data, c.Content); err != nil {
			return err
		}
		err := json.Unmarshal(data, &struct {
			ID *string `json:"id,omitempty"`
		}{
			ID: &c.ID,
		})
		if err != nil {
			return err
		}
	case "tool":
		if _, ok := raw["name"]; ok {
			c.ToolCall = &ToolCall{}
			if err := json.Unmarshal(data, c.ToolCall); err != nil {
				return err
			}
		}
		if _, ok := raw["output"]; ok {
			c.ToolCallResult = &ToolCallResult{}
			if err := json.Unmarshal(data, c.ToolCallResult); err != nil {
				return err
			}
		}
	case "reasoning":
		c.Reasoning = &Reasoning{}
		return json.Unmarshal(data, c.Reasoning)
	}

	return nil
}

func (c CompletionItem) MarshalJSON() ([]byte, error) {
	if c.ID == "" {
		c.ID = uuid.String()
	}

	if c.Content != nil {
		// mcp.Content has a custom MarshalJSON method that messes up things, so this is
		// a workaround to ensure we get the correct JSON structure.
		content, err := json.Marshal(c.Content)
		if err != nil {
			return nil, err
		}

		header, err := json.Marshal(map[string]any{
			"id":      c.ID,
			"hasMore": c.HasMore,
			"partial": c.Partial,
		})

		// length 2 means it is an empty object
		if len(header) == 2 {
			return content, nil
		} else if len(content) == 2 {
			return header, nil
		}

		return slices.Concat(header[:len(header)-1], []byte(","), content[1:]), nil
	} else if c.ToolCallResult != nil || c.ToolCall != nil {
		var (
			tc     ToolCall
			output CallResult
		)
		if c.ToolCall != nil {
			tc = *c.ToolCall
		} else {
			tc = ToolCall{
				CallID: c.ToolCallResult.CallID,
			}
		}
		if c.ToolCallResult != nil {
			output = c.ToolCallResult.Output
		}
		return json.Marshal(struct {
			ID      string     `json:"id,omitempty"`
			HasMore bool       `json:"hasMore,omitempty"`
			Partial bool       `json:"partial,omitempty"`
			Type    string     `json:"type,omitempty"`
			Output  CallResult `json:"output,omitzero"`
			ToolCall
		}{
			ID:       c.ID,
			Type:     "tool",
			HasMore:  c.HasMore,
			Partial:  c.Partial,
			ToolCall: tc,
			Output:   output,
		})
	} else if c.Reasoning != nil {
		return json.Marshal(struct {
			ID      string `json:"id,omitempty"`
			Type    string `json:"type,omitempty"`
			HasMore bool   `json:"hasMore,omitempty"`
			Partial bool   `json:"partial,omitempty"`
			*Reasoning
		}{
			ID:        c.ID,
			Type:      "reasoning",
			HasMore:   c.HasMore,
			Partial:   c.Partial,
			Reasoning: c.Reasoning,
		})
	}
	type Alias CompletionItem
	return json.Marshal(Alias(c))
}

type Reasoning struct {
	EncryptedContent string        `json:"encryptedContent,omitempty"`
	Summary          []SummaryText `json:"summary,omitempty"`
}

type SummaryText struct {
	Text string `json:"text,omitempty"`
}

type CompletionResponse struct {
	Output           Message   `json:"output,omitempty"`
	InternalMessages []Message `json:"internalMessages,omitempty"`
	Agent            string    `json:"agent,omitempty"`
	Model            string    `json:"model,omitempty"`
	HasMore          bool      `json:"hasMore,omitempty"`
	Error            string    `json:"error,omitempty"`
	ProgressToken    any       `json:"progressToken,omitempty"`
}

func (c *CompletionResponse) Serialize() (any, error) {
	return c, nil
}

func (c *CompletionResponse) Deserialize(data any) (any, error) {
	return c, mcp.JSONCoerce(data, &c)
}

type ToolCallResult struct {
	CallID string     `json:"callID,omitempty"`
	Output CallResult `json:"output,omitzero"`
	// NOTE: If you add fields here, make sure to update the CompletionItem.MarshalJSON method, it
	//has special handling for ToolCallResult.
}

type ToolCall struct {
	Arguments  string `json:"arguments,omitempty"`
	CallID     string `json:"callID,omitempty"`
	Name       string `json:"name,omitempty"`
	Target     string `json:"target,omitempty"`
	TargetType string `json:"targetType,omitempty"`
}

type CallResult struct {
	Content           []mcp.Content `json:"content,omitempty"`
	IsError           bool          `json:"isError,omitempty"`
	Agent             string        `json:"agent,omitempty"`
	Model             string        `json:"model,omitempty"`
	StopReason        string        `json:"stopReason,omitempty"`
	StructuredContent any           `json:"structuredContent,omitempty"`
}

type AsyncCallResult struct {
	IsError       bool          `json:"isError"`
	Content       []mcp.Content `json:"content,omitzero"`
	InProgress    bool          `json:"inProgress,omitempty"`
	ToolName      string        `json:"toolName,omitempty"`
	ProgressToken any           `json:"progressToken,omitempty"`
}
