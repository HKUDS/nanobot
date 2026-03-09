package mcp

import (
	"encoding/base64"
	"encoding/json"
	"time"

	"github.com/obot-platform/mcp-oauth-proxy/pkg/providers"
)

type User providers.UserInfo

type ClientCapabilities struct {
	Roots       *RootsCapability    `json:"roots,omitempty"`
	Sampling    *SamplingCapability `json:"sampling,omitempty"`
	Elicitation *struct{}           `json:"elicitation,omitempty"`
}

type SamplingCapability struct {
	Context *struct{} `json:"context,omitempty"`
	Tools   *struct{} `json:"tools,omitempty"`
}

type RootsCapability struct {
	ListChanged bool `json:"listChanged"`
}

type ClientInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type ServerCapabilities struct {
	Experimental map[string]any             `json:"experimental,omitempty"`
	Logging      *struct{}                  `json:"logging,omitempty"`
	Prompts      *PromptsServerCapability   `json:"prompts,omitempty"`
	Resources    *ResourcesServerCapability `json:"resources,omitempty"`
	Tools        *ToolsServerCapability     `json:"tools,omitempty"`
}

type ToolsServerCapability struct {
	ListChanged bool `json:"listChanged"`
}

type PromptsServerCapability struct {
	ListChanged bool `json:"listChanged"`
}

type ResourcesServerCapability struct {
	Subscribe   bool `json:"subscribe"`
	ListChanged bool `json:"listChanged"`
}

type ServerInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type InitializeResult struct {
	ProtocolVersion string             `json:"protocolVersion"`
	Capabilities    ServerCapabilities `json:"capabilities"`
	ServerInfo      ServerInfo         `json:"serverInfo"`
	Instructions    string             `json:"instructions"`
	Meta            map[string]any     `json:"_meta,omitzero"`
}

type InitializeRequest struct {
	ProtocolVersion string             `json:"protocolVersion"`
	Capabilities    ClientCapabilities `json:"capabilities"`
	ClientInfo      ClientInfo         `json:"clientInfo"`
	Meta            map[string]any     `json:"_meta,omitzero"`
}

type PingResult struct{}

type ElicitResult struct {
	// Action must be one of "accept", "decline", "cancel"
	Action  string         `json:"action"`
	Content map[string]any `json:"content,omitempty"`
}

type ElicitRequest struct {
	Mode            string          `json:"mode,omitempty"`
	Message         string          `json:"message,omitempty"`
	RequestedSchema PrimitiveSchema `json:"requestedSchema,omitzero"`
	URL             string          `json:"url,omitempty"`
	ElicitationID   string          `json:"elicitationId,omitempty"`
	Meta            json.RawMessage `json:"_meta,omitzero"`
}

type PrimitiveSchema struct {
	// Type must be "object" only
	Type       string                       `json:"type"`
	Properties map[string]PrimitiveProperty `json:"properties"`
	Required   []string                     `json:"required,omitempty"`
}

type PrimitiveProperty struct {
	// Type must be one of "string", "number", "boolean", "enum", "integer"
	Type        string       `json:"type"`
	Title       string       `json:"title,omitempty"`
	Description string       `json:"description,omitempty"`
	MinLength   *int         `json:"minLength,omitempty"`
	MaxLength   *int         `json:"maxLength,omitempty"`
	Minimum     *json.Number `json:"minimum,omitempty"`
	Maximum     *json.Number `json:"maximum,omitempty"`
	Default     any          `json:"default,omitempty"`
	Enum        []string     `json:"enum,omitempty"`
	EnumNames   []string     `json:"enumNames,omitempty"`
	// Format must be one of "date-time", "email", "uri", "date"
	Format string `json:"format,omitempty"`
}

type ModelPreferences struct {
	Hints                []ModelHint `json:"hints,omitzero"`
	CostPriority         *float64    `json:"costPriority"`
	SpeedPriority        *float64    `json:"speedPriority"`
	IntelligencePriority *float64    `json:"intelligencePriority"`
}

type ModelHint struct {
	Name string `json:"name"`
}
type CreateMessageRequest struct {
	Messages         []SamplingMessage `json:"messages,omitzero"`
	ModelPreferences ModelPreferences  `json:"modelPreferences,omitzero"`
	SystemPrompt     string            `json:"systemPrompt,omitzero"`
	IncludeContext   string            `json:"includeContext,omitempty"`
	MaxTokens        int               `json:"maxTokens,omitempty"`
	Temperature      *json.Number      `json:"temperature,omitempty"`
	StopSequences    []string          `json:"stopSequences,omitzero"`
	Metadata         map[string]any    `json:"metadata,omitempty"`
	ToolChoice       *ToolChoice       `json:"toolChoice,omitempty"`
	Tools            []Tool            `json:"tools,omitzero"`
}

type ToolChoice struct {
	// Mode must be one of "none", "auto", "required"
	Mode string `json:"mode"`
}

type ListRootsRequest struct{}

type ListRootsResult struct {
	Roots []Root `json:"roots"`
}

type Root struct {
	URI  string `json:"uri"`
	Name string `json:"name,omitempty"`
}

type LoggingMessage struct {
	Level  string `json:"level"`
	Logger string `json:"logger,omitempty"`
	Data   any    `json:"data"`
}

type SamplingMessage struct {
	Role    string   `json:"role,omitempty"`
	Content Contents `json:"content,omitempty"`
}

type Contents []Content

func (c Contents) MarshalJSON() ([]byte, error) {
	if len(c) == 1 {
		return json.Marshal(c[0])
	}
	type Alias Contents
	return json.Marshal((*Alias)(&c))
}

func (c *Contents) UnmarshalJSON(b []byte) error {
	if len(b) > 0 && b[0] == '{' {
		var content Content
		if err := json.Unmarshal(b, &content); err != nil {
			return err
		}
		*c = Contents{content}
	} else {
		var contents []Content
		if err := json.Unmarshal(b, &contents); err != nil {
			return err
		}
		*c = contents
	}
	return nil
}

type Content struct {
	Type string `json:"type,omitempty"`

	// Name is used for resource_link, tool_use
	Name string `json:"name,omitempty"`

	// Description is used for resource_link
	Description string `json:"description,omitempty"`

	// URI is used for resource_link
	URI string `json:"uri,omitempty"`

	// Text is set when type is "text"
	Text string `json:"text,omitempty"`

	// Data is set when type is "image" or "audio"
	Data string `json:"data,omitempty"`

	// MIMEType is set when type is "image" or "audio" or "resource_link"
	MIMEType string `json:"mimeType,omitempty"`

	// Resource is set when type is "resource"
	Resource *EmbeddedResource `json:"resource,omitempty"`

	// Meta is used for all types and contains arbitrary metadata.
	Meta map[string]any `json:"_meta,omitempty"`

	// ID is used for tool_use
	ID string `json:"id,omitempty"`

	// Input is used for tool_use
	Input map[string]any `json:"input,omitempty"`

	// ToolUseID is used for tool_result
	ToolUseID string `json:"toolUseId,omitempty"`

	// Content is used for tool_result
	Content []Content `json:"content,omitempty"`

	// StructuredContent is used for tool_result
	StructuredContent map[string]any `json:"structuredContent,omitempty"`

	// IsError is used for tool_result
	IsError bool `json:"isError,omitempty"`
}

func (c Content) MarshalJSON() ([]byte, error) {
	type Alias Content
	if c.Type == "" {
		if c.Resource != nil {
			c.Type = "resource"
		} else if c.Text != "" {
			c.Type = "text"
		} else if c.Data != "" {
			c.Type = "image"
		} else if c.URI != "" {
			c.Type = "resource_link"
		} else if c.ToolUseID != "" {
			c.Type = "tool_result"
		} else if c.ID != "" {
			c.Type = "tool_use"
		}
	}
	return json.Marshal((*Alias)(&c))
}

type CreateMessageResult struct {
	Content    Contents `json:"content,omitempty"`
	Role       string   `json:"role,omitempty"`
	Model      string   `json:"model,omitempty"`
	StopReason string   `json:"stopReason,omitempty"`
}

func (c *Content) ToImageURL() string {
	return "data:" + c.MIMEType + ";base64," + c.Data
}

type EmbeddedResource struct {
	URI         string               `json:"uri,omitempty"`
	Name        string               `json:"name,omitempty"`
	Title       string               `json:"title,omitempty"`
	MIMEType    string               `json:"mimeType,omitempty"`
	Text        string               `json:"text,omitempty"`
	Blob        string               `json:"blob,omitempty"`
	Annotations *ResourceAnnotations `json:"annotations,omitempty"`
	Meta        map[string]any       `json:"_meta,omitempty"`
}

func (e *EmbeddedResource) ToDataURI() string {
	if e.Text != "" {
		return "data:" + e.MIMEType + ";base64," + base64.StdEncoding.EncodeToString([]byte(e.Text))
	}
	return "data:" + e.MIMEType + ";base64," + e.Blob
}

type ResourceAnnotations struct {
	Audience     []string    `json:"audience,omitempty"`
	Priority     json.Number `json:"priority,omitempty"`
	LastModified time.Time   `json:"lastModified,omitzero"`
}

type Tool struct {
	Name         string           `json:"name"`
	Title        string           `json:"title,omitempty"`
	Icons        []Icon           `json:"icons,omitzero"`
	Description  string           `json:"description,omitempty"`
	InputSchema  json.RawMessage  `json:"inputSchema,omitzero"`
	OutputSchema json.RawMessage  `json:"outputSchema,omitzero"`
	Annotations  *ToolAnnotations `json:"annotations,omitempty"`
	Meta         map[string]any   `json:"_meta,omitzero"`
}

type Icons struct {
	Icons []Icon `json:"icons,omitzero"`
}

type Icon struct {
	Src      string   `json:"src"`
	MIMEType string   `json:"mimeType,omitempty"`
	Sizes    []string `json:"sizes,omitzero"`
}

type ToolAnnotations struct {
	Title           string `json:"title,omitempty"`
	ReadOnlyHint    bool   `json:"readOnlyHint,omitempty"`
	DestructiveHint *bool  `json:"destructiveHint,omitempty"`
	IdempotentHint  bool   `json:"idempotentHint,omitempty"`
	OpenWorldHint   *bool  `json:"openWorldHint,omitempty"`
}

func (t ToolAnnotations) IsOpenWorld() bool {
	if t.OpenWorldHint == nil {
		return true
	}
	return *t.OpenWorldHint
}

func (t ToolAnnotations) IsDestructive() bool {
	if t.DestructiveHint == nil {
		return true
	}
	return *t.DestructiveHint
}

type CallToolResult struct {
	IsError           bool      `json:"isError"`
	Content           []Content `json:"content,omitzero"`
	StructuredContent any       `json:"structuredContent,omitempty"`
}

type CallToolRequest struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments,omitempty"`
	Meta      map[string]any `json:"_meta,omitzero"`
}

var EmptyObjectSchema = json.RawMessage(`{"type": "object", "properties": {}, "additionalProperties": false, "required": []}`)

type ListToolsRequest struct{}

type ListToolsResult struct {
	Tools []Tool `json:"tools"`
}

type GetPromptRequest struct {
	Name      string            `json:"name"`
	Arguments map[string]string `json:"arguments,omitempty"`
}

type GetPromptResult struct {
	Description string          `json:"description,omitempty"`
	Messages    []PromptMessage `json:"messages"`
}

type PromptMessage struct {
	Role    string  `json:"role"`
	Content Content `json:"content"`
}

type ReadResourceRequest struct {
	URI string `json:"uri"`
}

type ReadResourceResult struct {
	Contents []ResourceContent `json:"contents"`
}

func (s ReadResourceResult) MarshalJSON() ([]byte, error) {
	if s.Contents == nil {
		s.Contents = []ResourceContent{}
	}
	type Alias ReadResourceResult
	return json.Marshal((*Alias)(&s))
}

type ResourceContent struct {
	URI      string         `json:"uri"`
	Name     string         `json:"name"`
	MIMEType string         `json:"mimeType"`
	Text     *string        `json:"text,omitempty"`
	Blob     *string        `json:"blob,omitempty"`
	Meta     map[string]any `json:"_meta,omitempty"`
}

func (r ResourceContent) ToDataURI() string {
	if r.Text != nil {
		return "data:" + r.MIMEType + ";base64," + base64.StdEncoding.EncodeToString([]byte(*r.Text))
	}
	if r.Blob != nil {
		return "data:" + r.MIMEType + ";base64," + *r.Blob
	}
	return "data:" + r.MIMEType + ";base64,"
}

type ListResourceTemplatesRequest struct{}

type ListResourceTemplatesResult struct {
	ResourceTemplates []ResourceTemplate `json:"resourceTemplates"`
}

type SubscribeRequest struct {
	URI string `json:"uri"`
}

type SubscribeResult struct{}

type UnsubscribeRequest struct {
	URI string `json:"uri"`
}

type UnsubscribeResult struct{}

type ResourceTemplate struct {
	URITemplate string       `json:"uriTemplate"`
	Name        string       `json:"name"`
	Description string       `json:"description,omitempty"`
	MimeType    string       `json:"mimeType,omitempty"`
	Annotations *Annotations `json:"annotations,omitempty"`
}

type ListResourcesRequest struct{}

type ListResourcesResult struct {
	Resources []Resource `json:"resources"`
}

type Resource struct {
	Icons
	URI         string         `json:"uri"`
	Name        string         `json:"name"`
	Title       string         `json:"title,omitempty"`
	Description string         `json:"description,omitempty"`
	MimeType    string         `json:"mimeType,omitempty"`
	Annotations *Annotations   `json:"annotations,omitempty"`
	Size        int64          `json:"size,omitempty"`
	Meta        map[string]any `json:"_meta,omitempty"`
}

type Annotations struct {
	Audience     []string    `json:"audience,omitempty"`
	Priority     json.Number `json:"priority,omitempty"`
	LastModified time.Time   `json:"lastModified,omitzero"`
}

type ListPromptsRequest struct{}

type ListPromptsResult struct {
	Prompts []Prompt `json:"prompts"`
}

type Prompt struct {
	Name        string           `json:"name"`
	Description string           `json:"description,omitempty"`
	Arguments   []PromptArgument `json:"arguments,omitempty"`
}

type PromptArgument struct {
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	Required    bool   `json:"required,omitempty"`
}

type Notification struct{}

type NotificationProgressRequest struct {
	ProgressToken any            `json:"progressToken"`
	Progress      json.Number    `json:"progress"`
	Total         *json.Number   `json:"total,omitempty"`
	Message       string         `json:"message,omitempty"`
	Meta          map[string]any `json:"_meta,omitzero"`
}

type SetLogLevelRequest struct {
	Level string `json:"level"`
}

type SetLogLevelResult struct{}

type SessionMessageHook struct {
	Accept  bool     `json:"accept"`
	Message *Message `json:"message"`
	Reason  string   `json:"reason"`
}

type CancelledNotification struct {
	RequestID any    `json:"requestId"`
	Reason    string `json:"reason,omitempty"`
}

type CancelledNotificationResult struct{}
