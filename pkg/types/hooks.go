package types

import (
	"context"
	"encoding/json"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

// AgentConfigHook is a hook that can be used to configure the agent.
// Hook Name = "config"
type AgentConfigHook struct {
	Agent      *HookAgent                          `json:"agent,omitempty"`
	Meta       map[string]any                      `json:"_meta,omitempty"`
	SessionID  string                              `json:"sessionId,omitempty"`
	MCPServers map[string]AgentConfigHookMCPServer `json:"mcpServers,omitempty"`
}

type HookAgent struct {
	Name            string                    `json:"name,omitempty"`
	ShortName       string                    `json:"shortName,omitempty"`
	Description     string                    `json:"description,omitempty"`
	Icon            string                    `json:"icon,omitempty"`
	IconDark        string                    `json:"iconDark,omitempty"`
	StarterMessages StringList                `json:"starterMessages,omitempty"`
	Instructions    DynamicInstructions       `json:"instructions,omitzero"`
	Model           string                    `json:"model,omitempty"`
	Permissions     *AgentPermissions         `json:"permissions,omitempty"`
	MCPServers      StringList                `json:"mcpServers,omitempty"`
	Tools           StringList                `json:"tools,omitempty"`
	Agents          StringList                `json:"agents,omitempty"`
	Prompts         StringList                `json:"prompts,omitzero"`
	Resources       StringList                `json:"resources,omitzero"`
	Reasoning       *AgentReasoning           `json:"reasoning,omitempty"`
	ThreadName      string                    `json:"threadName,omitempty"`
	Chat            *bool                     `json:"chat,omitempty"`
	ToolExtensions  map[string]map[string]any `json:"toolExtensions,omitempty"`
	ToolChoice      string                    `json:"toolChoice,omitempty"`
	Temperature     *json.Number              `json:"temperature,omitempty"`
	TopP            *json.Number              `json:"topP,omitempty"`
	Truncation      string                    `json:"truncation,omitempty"`
	MaxTokens       int                       `json:"maxTokens,omitempty"`
	ContextWindow   int                       `json:"contextWindow,omitempty"`
	MimeTypes       []string                  `json:"mimeTypes,omitempty"`
	Hooks           mcp.Hooks                 `json:"hooks,omitempty"`

	// Selection criteria fields

	Aliases      []string `json:"aliases,omitempty"`
	Cost         float64  `json:"cost,omitempty"`
	Speed        float64  `json:"speed,omitempty"`
	Intelligence float64  `json:"intelligence,omitempty"`
}

type AgentConfigHookMCPServer struct {
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers"`
}

func (a AgentConfigHookMCPServer) ToMCPServer() mcp.Server {
	return mcp.Server{
		BaseURL: a.URL,
		Headers: a.Headers,
	}
}

// AgentRequestHook is a hook that can be used to modify the request before it is sent to the MCP server.
// Hook Name = "request"
type AgentRequestHook struct {
	Request  *CompletionRequest  `json:"request,omitempty"`
	Response *CompletionResponse `json:"response,omitempty"`
}

// AgentResponseHook is a hook that can be used to modify the response before it is returned to the agent.
// Hook Name = "response"
type AgentResponseHook = AgentRequestHook

type SessionInitHook struct {
	URL       string         `json:"url"`
	SessionID string         `json:"sessionId"`
	Meta      map[string]any `json:"_meta,omitempty"`
}

func (s *SessionInitHook) Serialize() (any, error) {
	return s, nil
}

func (s *SessionInitHook) Deserialize(data any) (any, error) {
	return s, mcp.JSONCoerce(data, &s)
}

func IsUISession(ctx context.Context) bool {
	session := mcp.SessionFromContext(ctx)
	var sessionInit SessionInitHook
	session.Get(SessionInitSessionKey, &sessionInit)
	isUI, _ := sessionInit.Meta["ui"].(bool)
	return isUI
}

func IsChatSession(ctx context.Context) bool {
	session := mcp.SessionFromContext(ctx)
	var sessionInit SessionInitHook
	session.Get(SessionInitSessionKey, &sessionInit)
	isChat, _ := sessionInit.Meta["chat"].(bool)
	return isChat
}

func GetWorkspaceID(ctx context.Context) string {
	var sessionInit SessionInitHook
	mcp.SessionFromContext(ctx).Get(SessionInitSessionKey, &sessionInit)
	workspace, _ := sessionInit.Meta["workspace"].(map[string]any)
	id, _ := workspace["id"].(string)
	return id
}
