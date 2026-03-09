package types

import "github.com/nanobot-ai/nanobot/pkg/mcp"

const PreviousExecutionKey = "thread"

type Execution struct {
	Request           CompletionRequest     `json:"request,omitempty"`
	Done              bool                  `json:"done,omitempty"`
	PopulatedRequest  *CompletionRequest    `json:"populatedRequest,omitempty"`
	ToolToMCPServer   ToolMappings          `json:"toolToMCPServer,omitempty"`
	Response          *CompletionResponse   `json:"response,omitempty"`
	ToolOutputs       map[string]ToolOutput `json:"toolOutputs,omitempty"`
	CompactedMessages []Message             `json:"compactedMessages,omitempty"`
}

func (e *Execution) Serialize() (any, error) {
	return e, nil
}

func (e *Execution) Deserialize(data any) (any, error) {
	return e, mcp.JSONCoerce(data, e)
}

type ToolOutput struct {
	Output Message `json:"output,omitempty"`
	Done   bool    `json:"done,omitempty"`
}
