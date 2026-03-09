package types

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"iter"
	"regexp"
	"slices"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"gopkg.in/yaml.v3"
)

const (
	ConfigSessionKey                = "config"
	ConfigHashSessionKey            = "configHash"
	CurrentAgentSessionKey          = "currentAgent"
	SessionInitSessionKey           = "sessionInit"
	DefaultAgentSessionKey          = "defaultAgent"
	AccountIDSessionKey             = "accountID"
	DescriptionSessionKey           = "description"
	ResourceSubscriptionsSessionKey = "resourceSubscriptions"
	PublicURLSessionKey             = "publicURL"
)

type configContextKey struct{}

func ConfigFromContext(ctx context.Context) (result Config) {
	config, ok := ctx.Value(configContextKey{}).(Config)
	if ok {
		return config
	}
	mcp.SessionFromContext(ctx).Get(ConfigSessionKey, &result)
	return
}

func WithConfig(ctx context.Context, config Config) context.Context {
	return context.WithValue(ctx, configContextKey{}, config)
}

func GetSessionAndAccountID(ctx context.Context) (string, string) {
	var (
		session   = mcp.SessionFromContext(ctx).Root()
		accountID string
	)
	session.Get(AccountIDSessionKey, &accountID)
	return session.ID(), accountID
}

func CurrentAgent(ctx context.Context) string {
	var (
		session      = mcp.SessionFromContext(ctx)
		currentAgent string
		c            Config
	)
	if !session.Get(CurrentAgentSessionKey, &currentAgent) {
		if !session.Get(DefaultAgentSessionKey, &currentAgent) {
			session.Get(ConfigSessionKey, &c)
			if len(c.Publish.Entrypoint) > 0 {
				currentAgent = c.Publish.Entrypoint[0]
			}
		}
	}
	return currentAgent
}

type Config struct {
	Auth             *Auth                 `json:"auth,omitempty"`
	Extends          StringList            `json:"extends,omitempty"`
	Env              map[string]EnvDef     `json:"env,omitempty"`
	Publish          Publish               `json:"publish,omitzero"`
	Agents           map[string]Agent      `json:"agents,omitempty"`
	MCPServers       map[string]mcp.Server `json:"mcpServers,omitempty"`
	Profiles         map[string]Config     `json:"profiles,omitempty"`
	Prompts          map[string]Prompt     `json:"prompts,omitempty"`
	Hooks            mcp.Hooks             `json:"hooks,omitempty"`
	WorkspaceID      string                `json:"workspaceId,omitempty"`
	WorkspaceBaseURI string                `json:"workspaceBaseUri,omitempty"`
}

type ConfigFactory func(ctx context.Context, profiles string) (Config, error)

func (c Config) Redacted() Config {
	redacted := c

	for i, env := range redacted.Env {
		if env.Sensitive == nil || *env.Sensitive {
			env.Default = fmt.Sprintf("%s...", env.Default[:min(10, len(env.Default)/2)])
			redacted.Env[i] = env
		}
	}

	for _, mcpServer := range redacted.MCPServers {
		for key, val := range mcpServer.Env {
			mcpServer.Env[key] = fmt.Sprintf("%s...", val[:min(10, len(val)/2)])
		}

		for key, val := range mcpServer.Headers {
			mcpServer.Headers[key] = fmt.Sprintf("%s...", val[:min(10, len(val)/2)])
		}

	}

	for key, val := range c.Profiles {
		c.Profiles[key] = val.Redacted()
	}

	return redacted
}

func (c Config) Validate(allowLocal bool) error {
	var (
		errs      []error
		seenNames = map[string]string{}
	)

	if len(c.Publish.Entrypoint) == 0 && len(c.Agents) > 1 {
		errs = append(errs, fmt.Errorf("publish must have at least one entrypoint agent set if there are multiple agents"))
	}

	for _, extend := range c.Extends {
		if strings.HasPrefix(strings.TrimSpace(extend), "/") {
			errs = append(errs, fmt.Errorf("extends cannot be an absolute path: %s", c.Extends))
		}
	}

	for agentName, agent := range c.Agents {
		if err := checkDup(seenNames, "agents", agentName); err != nil {
			errs = append(errs, err)
		}
		if err := agent.validate(agentName, c); err != nil {
			errs = append(errs, err)
		}
	}

	for mcpServerName, mcpServer := range c.MCPServers {
		if err := checkDup(seenNames, "mcpServers", mcpServerName); err != nil {
			errs = append(errs, err)
		}
		if err := validateMCPServer(mcpServerName, mcpServer, allowLocal); err != nil {
			errs = append(errs, err)
		}
	}

	return errors.Join(errs...)
}

func validateMCPServer(mcpServerName string, mcpServer mcp.Server, allowLocal bool) error {
	if allowLocal {
		return nil
	}

	if mcpServer.Source.Repo != "" {
		if !strings.HasPrefix(mcpServer.Source.Repo, "https://") &&
			!strings.HasPrefix(mcpServer.Source.Repo, "http://") &&
			!strings.HasPrefix(mcpServer.Source.Repo, "git@") &&
			!strings.HasPrefix(mcpServer.Source.Repo, "ssh://") {
			return fmt.Errorf("mcpServer %q has invalid repo URL %q, must start with http://, https://, git@, or ssh://", mcpServerName, mcpServer.Source.Repo)
		}
	}

	return nil
}

type Prompt struct {
	Description string           `json:"description,omitempty"`
	Input       map[string]Field `json:"input,omitempty"`
	Template    string           `json:"template,omitempty"`
}

func (p Prompt) ToPrompt(name string) mcp.Prompt {
	result := mcp.Prompt{
		Name:        name,
		Description: p.Description,
	}
	for fieldName, field := range p.Input {
		result.Arguments = append(result.Arguments, mcp.PromptArgument{
			Name:        fieldName,
			Description: field.Description,
			Required:    field.Required == nil || *field.Required,
		})
	}
	return result
}

type Auth struct {
	OAuthClientID                    string         `json:"oauthClientId"`
	OAuthClientSecret                string         `json:"oauthClientSecret"`
	OAuthAuthorizeURL                string         `json:"oauthAuthorizeUrl"`
	OAuthScopes                      StringList     `json:"oauthScopes"`
	OAuthAuthorizationServerMetadata map[string]any `json:"oauthAuthorizationServerMetadata"`
	EncryptionKey                    string         `json:"encryptionKey"`
	APIKeyAuthURL                    string         `json:"apiKeyAuthUrl"`
}

type EnvDef struct {
	Default        string     `json:"default,omitempty"`
	Description    string     `json:"description,omitempty"`
	Options        StringList `json:"options,omitempty"`
	Optional       bool       `json:"optional,omitempty"`
	Sensitive      *bool      `json:"sensitive,omitempty"`
	UseBearerToken bool       `json:"useBearerToken,omitempty"`
}

func (e *EnvDef) UnmarshalJSON(data []byte) error {
	if data[0] == '"' && data[len(data)-1] == '"' {
		var raw string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		e.Description = raw
		return nil
	}
	type Alias EnvDef
	return json.Unmarshal(data, (*Alias)(e))
}

type Publish struct {
	Name              string              `json:"name,omitempty"`
	Introduction      DynamicInstructions `json:"introduction,omitzero"`
	Version           string              `json:"version,omitempty"`
	Instructions      string              `json:"instructions,omitempty"`
	Tools             StringList          `json:"tools,omitzero"`
	Prompts           StringList          `json:"prompts,omitzero"`
	Resources         StringList          `json:"resources,omitzero"`
	ResourceTemplates StringList          `json:"resourceTemplates,omitzero"`
	MCPServers        StringList          `json:"mcpServers,omitzero"`
	Entrypoint        StringList          `json:"entrypoint,omitempty"`
}

func (p Publish) IsSingleServerProxy() bool {
	return len(p.MCPServers) == 1 &&
		len(p.Entrypoint) == 0 &&
		len(p.Tools) == 0 &&
		len(p.Resources) == 0 &&
		len(p.Prompts) == 0 &&
		len(p.ResourceTemplates) == 0 &&
		p.Instructions == ""
}

type ToolRef struct {
	Server string
	Tool   string
	As     string
}

func (t ToolRef) PublishedName(name string) string {
	if t.As != "" {
		return t.As
	}
	if t.Tool != "" {
		return t.Tool
	}
	if name == "" {
		return t.Server
	}
	return name
}

func (t ToolRef) String() string {
	if t.As != "" {
		return fmt.Sprintf("%s:%s/%s", t.As, t.Server, t.Tool)
	}
	if t.Tool == "" {
		return t.Server
	}
	return fmt.Sprintf("%s/%s", t.Server, t.Tool)
}

func ParseToolRef(ref string) ToolRef {
	name, as, _ := strings.Cut(ref, ":")
	server, tool, _ := strings.Cut(name, "/")
	return ToolRef{
		Server: server,
		Tool:   tool,
		As:     as,
	}
}

type ResourceMappings map[string]TargetMapping[mcp.Resource]

func (r ResourceMappings) Deserialize(data any) (any, error) {
	return r, mcp.JSONCoerce(data, &r)
}

type ResourceTemplateMappings map[string]TargetMapping[TemplateMatch]

func (r ResourceTemplateMappings) Deserialize(data any) (any, error) {
	return r, mcp.JSONCoerce(data, &r)
}

type TemplateMatch struct {
	Regexp           *regexp.Regexp
	ResourceTemplate mcp.ResourceTemplate
}

func (t *TemplateMatch) UnmarshalJSON(data []byte) error {
	var raw struct {
		Regexp           string               `json:"regexp"`
		ResourceTemplate mcp.ResourceTemplate `json:"resourceTemplate"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	if raw.Regexp != "" {
		regexp, err := regexp.Compile(raw.Regexp)
		if err != nil {
			return fmt.Errorf("failed to compile regexp %q: %w", raw.Regexp, err)
		}
		t.Regexp = regexp
	} else {
		t.Regexp = nil
	}

	t.ResourceTemplate = raw.ResourceTemplate
	return nil
}

func (t TemplateMatch) MarshalJSON() ([]byte, error) {
	var regexp string
	if t.Regexp != nil {
		regexp = t.Regexp.String()
	}
	return json.Marshal(map[string]any{
		"regexp":           regexp,
		"resourceTemplate": t.ResourceTemplate,
	})
}

type PromptMappings map[string]TargetMapping[mcp.Prompt]

//func (p PromptMappings) Serialize() (any, error) {
//	return p, nil
//}

func (p PromptMappings) Deserialize(data any) (any, error) {
	return p, mcp.JSONCoerce(data, &p)
}

type TargetMapping[T any] struct {
	MCPServer  string `json:"mcpServer,omitempty"`
	TargetName string `json:"targetName,omitempty"`
	Target     T      `json:"target,omitempty"`
}

type TargetTool struct {
	mcp.Tool
	External bool `json:"external,omitempty"`
}
type ToolMappings map[string]TargetMapping[TargetTool]

//func (t ToolMappings) Serialize() (any, error) {
//	return t, nil
//}

func (t *ToolMappings) Deserialize(data any) (any, error) {
	return t, mcp.JSONCoerce(data, &t)
}

type BuildToolMappingsOptions struct {
	DefaultAsToServer bool
}

func (b BuildToolMappingsOptions) Merge(other BuildToolMappingsOptions) BuildToolMappingsOptions {
	b.DefaultAsToServer = complete.Last(b.DefaultAsToServer, other.DefaultAsToServer)
	return b
}

type StringList []string

func (s *StringList) UnmarshalJSON(data []byte) error {
	if data[0] == '[' && data[len(data)-1] == ']' {
		var raw []string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		*s = raw
	} else {
		var raw string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		var list []string
		for item := range strings.SplitSeq(raw, ",") {
			list = append(list, strings.TrimSpace(item))
		}
		*s = list
	}
	return nil
}

type Agent struct {
	HookAgent `json:",inline" yaml:",inline"`
	Output    *OutputSchema `json:"output,omitempty"`
}

type AgentReasoning struct {
	Effort  string `json:"effort,omitempty"`
	Summary string `json:"summary,omitempty"`
}

func (a Agent) ToDisplay(id string) AgentDisplay {
	agent := AgentDisplay{
		ID:              id,
		Name:            a.Name,
		ShortName:       a.ShortName,
		Description:     a.Description,
		Icon:            a.Icon,
		IconDark:        a.IconDark,
		StarterMessages: a.StarterMessages,
		Base:            true,
	}
	if agent.Name == "" {
		agent.Name = agent.ShortName
	}
	if agent.Name == "" {
		agent.Name = agent.ID
	}
	return agent
}

type AgentPermission string

const (
	AgentPermissionUnset AgentPermission = ""
	AgentPermissionAllow AgentPermission = "allow"
	AgentPermissionDeny  AgentPermission = "deny"
)

var denyAll = [][2]string{
	{"*", string(AgentPermissionDeny)},
}

func DenyAllPermissions() *AgentPermissions {
	return &AgentPermissions{
		permissions: denyAll,
	}
}

type AgentPermissions struct {
	permissions [][2]string `json:"-"`
}

// Allowed returns a list of the allowed permissions from the input.
func (a *AgentPermissions) Allowed(from iter.Seq[string]) []string {
	if a == nil || len(a.permissions) == 0 {
		return slices.Collect(from)
	}

	var allowed []string
	for perm := range from {
		if a.IsAllowed(perm) {
			allowed = append(allowed, perm)
		}
	}
	return allowed
}

// IsAllowed returns true if the permission is allowed.
func (a *AgentPermissions) IsAllowed(perm string) bool {
	for _, pair := range slices.Backward(a.permissions) {
		if pair[0] == perm || pair[0] == "*" {
			return pair[1] == string(AgentPermissionAllow)
		}
	}
	return true
}

func (a *AgentPermissions) UnmarshalJSON(data []byte) error {
	// Parse as a generic map to preserve order using json.RawMessage
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	// We need to preserve order, so we'll decode in the order keys appear in the original JSON
	// Since Go's map doesn't preserve order, we'll parse the raw JSON to extract key order
	decoder := json.NewDecoder(strings.NewReader(string(data)))

	// Read opening brace
	if _, err := decoder.Token(); err != nil {
		return err
	}

	a.permissions = nil

	// Read key-value pairs in order
	for decoder.More() {
		// Read key
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		key, ok := token.(string)
		if !ok {
			return fmt.Errorf("expected string key, got %T", token)
		}

		// Read value
		var value string
		if err := decoder.Decode(&value); err != nil {
			return err
		}

		a.permissions = append(a.permissions, [2]string{key, value})
	}

	// Read closing brace
	if _, err := decoder.Token(); err != nil {
		return err
	}

	return nil
}

func (a AgentPermissions) MarshalJSON() ([]byte, error) {
	// Use a custom approach to maintain order
	if len(a.permissions) == 0 {
		return []byte("{}"), nil
	}

	var buf strings.Builder
	buf.WriteString("{")

	for i, pair := range a.permissions {
		if i > 0 {
			buf.WriteString(",")
		}

		// Marshal key
		keyJSON, err := json.Marshal(pair[0])
		if err != nil {
			return nil, err
		}
		buf.Write(keyJSON)
		buf.WriteString(":")

		// Marshal value
		valueJSON, err := json.Marshal(pair[1])
		if err != nil {
			return nil, err
		}
		buf.Write(valueJSON)
	}

	buf.WriteString("}")
	return []byte(buf.String()), nil
}

func (a *AgentPermissions) UnmarshalYAML(value *yaml.Node) error {
	// YAML should be a mapping node
	if value.Kind != yaml.MappingNode {
		return fmt.Errorf("expected mapping node, got %v", value.Kind)
	}

	a.permissions = nil

	// YAML mapping nodes have alternating key-value pairs in Content slice
	// Keys are at even indices, values at odd indices
	for i := 0; i < len(value.Content); i += 2 {
		keyNode := value.Content[i]
		valueNode := value.Content[i+1]

		if keyNode.Kind != yaml.ScalarNode {
			return fmt.Errorf("expected scalar key, got %v", keyNode.Kind)
		}
		if valueNode.Kind != yaml.ScalarNode {
			return fmt.Errorf("expected scalar value, got %v", valueNode.Kind)
		}

		a.permissions = append(a.permissions, [2]string{keyNode.Value, valueNode.Value})
	}

	return nil
}

func (a AgentPermissions) MarshalYAML() (any, error) {
	// Create a yaml.Node with mapping style
	node := &yaml.Node{
		Kind: yaml.MappingNode,
	}

	// Add key-value pairs in order
	for _, pair := range a.permissions {
		// Add key node
		node.Content = append(node.Content, &yaml.Node{
			Kind:  yaml.ScalarNode,
			Value: pair[0],
		})
		// Add value node
		node.Content = append(node.Content, &yaml.Node{
			Kind:  yaml.ScalarNode,
			Value: pair[1],
		})
	}

	return node, nil
}

const mcpServerName = "MCP Server"

func validateReference[T any](ref string, targetType string, targets map[string]T) (string, error) {
	if targetType != mcpServerName && strings.Contains(ref, "/") {
		return "", fmt.Errorf("invalid %s reference %q: slashes are not allowed", targetType, ref)
	}

	toolRef := ParseToolRef(ref)
	if _, ok := targets[toolRef.Server]; !ok {
		return "", fmt.Errorf("can not find %s %q, missing in config", targetType, ref)
	}

	if targetType == mcpServerName {
		return toolRef.PublishedName(""), nil
	}

	return toolRef.PublishedName(toolRef.Server), nil
}

func validateReferences(c Config, tools, agents StringList) (bool, map[string]struct{}, []error) {
	var (
		errs              []error
		unknownNames      bool
		resolvedToolNames = make(map[string]struct{})
	)

	for _, ref := range tools {
		targetName, err := validateReference(ref, mcpServerName, c.MCPServers)
		if err != nil {
			errs = append(errs, fmt.Errorf("error validating tool reference %q: %w", ref, err))
		}
		if targetName == "" {
			unknownNames = true
		} else {
			resolvedToolNames[targetName] = struct{}{}
		}
	}

	for _, ref := range agents {
		targetName, err := validateReference(ref, "agent", c.Agents)
		if err != nil {
			errs = append(errs, fmt.Errorf("error validating agent reference %q: %w", ref, err))
		}
		resolvedToolNames[targetName] = struct{}{}
	}

	return unknownNames, resolvedToolNames, errs
}

func (a Agent) validate(agentName string, c Config) error {
	unknownNames, resolvedToolNames, errs := validateReferences(c, a.Tools, a.Agents)

	if a.Instructions.IsSet() && a.Instructions.IsPrompt() {
		_, ok := c.MCPServers[a.Instructions.MCPServer]
		if !ok {
			errs = append(errs, fmt.Errorf("agent %q has instructions with MCP server %q that is not defined in config", agentName, a.Instructions.MCPServer))
		}
	}

	for _, mcpServer := range a.MCPServers {
		if _, ok := c.MCPServers[mcpServer]; !ok {
			errs = append(errs, fmt.Errorf("agent %q has MCP server %q that is not defined in config", agentName, mcpServer))
		}
	}

	if !unknownNames && a.ToolChoice != "" && a.ToolChoice != "none" && a.ToolChoice != "auto" {
		if _, ok := resolvedToolNames[a.ToolChoice]; !ok {
			errs = append(errs, fmt.Errorf("agent %q has tool choice %q that is not defined in tools", agentName, a.ToolChoice))
		}
	}

	return errors.Join(errs...)
}

type DynamicInstructions struct {
	Instructions string            `json:"-"`
	MCPServer    string            `json:"mcpServer,omitempty"`
	Prompt       string            `json:"prompt,omitempty"`
	Args         map[string]string `json:"args,omitempty"`
}

func (a DynamicInstructions) IsPrompt() bool {
	return a.MCPServer != "" && a.Prompt != ""
}

func (a DynamicInstructions) IsSet() bool {
	return a.IsPrompt() || a.Instructions != ""
}

func (a *DynamicInstructions) UnmarshalJSON(data []byte) error {
	if data[0] == '"' && data[len(data)-1] == '"' {
		var raw string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		a.Instructions = raw
		return nil
	}
	type Alias DynamicInstructions
	return json.Unmarshal(data, (*Alias)(a))
}

func (a DynamicInstructions) MarshalJSON() ([]byte, error) {
	if a.Instructions != "" {
		return json.Marshal(a.Instructions)
	}
	type Alias DynamicInstructions
	return json.Marshal(Alias(a))
}

type OutputSchema struct {
	Name        string           `json:"name,omitempty"`
	Description string           `json:"description,omitempty"`
	Schema      json.RawMessage  `json:"schema,omitzero"`
	Strict      bool             `json:"strict,omitempty"`
	Fields      map[string]Field `json:"fields,omitempty"`
}

type Field struct {
	Description string           `json:"description,omitempty"`
	Fields      map[string]Field `json:"fields,omitempty"`
	Required    *bool            `json:"required,omitempty"`
}

func (f *Field) UnmarshalJSON(data []byte) error {
	if data[0] == '"' && data[len(data)-1] == '"' {
		var raw string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		f.Description = raw
		f.Fields = nil
		return nil
	}
	type Alias Field
	return json.Unmarshal(data, (*Alias)(f))
}

func (f Field) MarshalJSON() ([]byte, error) {
	if len(f.Fields) > 0 {
		type Alias Field
		return json.Marshal(Alias(f))
	}
	return json.Marshal(f.Description)
}

func (o OutputSchema) ToSchema() json.RawMessage {
	if len(o.Fields) > 0 {
		data, _ := json.Marshal(buildSimpleSchema(o.Name, o.Description, o.Fields))
		return data
	}
	return o.Schema
}

type InputSchema struct {
	Name        string           `json:"name,omitempty"`
	Description string           `json:"description,omitempty"`
	Schema      json.RawMessage  `json:"schema,omitzero"`
	Fields      map[string]Field `json:"fields,omitempty"`
}

func (i InputSchema) ToSchema() json.RawMessage {
	if len(i.Fields) > 0 {
		data, _ := json.Marshal(buildSimpleSchema(i.Name, i.Description, i.Fields))
		return data
	}
	return i.Schema
}

// enumSyntaxRegexp is string like name(option1,option2,option3). This is not a complete regex for enum syntax,
// but it is used to detect if a field is an enum based on the presence of parentheses.
var enumSyntaxRegexp = regexp.MustCompile(`^.+\(.+,`)

func buildSimpleSchema(name, description string, args map[string]Field) map[string]any {
	required := make([]string, 0)
	jsonschema := map[string]any{
		"type":                 "object",
		"properties":           map[string]any{},
		"additionalProperties": false,
	}

	if name != "" {
		jsonschema["title"] = name
	}

	if description != "" {
		jsonschema["description"] = description
	}

	for name, field := range args {
		if strings.HasSuffix(name, "[]") {
			name = strings.TrimSuffix(name, "[]")
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "array",
				"description": field.Description,
				"items": map[string]any{
					"type": "string",
				},
			}
			if len(field.Fields) > 0 {
				jsonschema["properties"].(map[string]any)[name].(map[string]any)["items"] =
					buildSimpleSchema("", "", field.Fields)
			}
		} else if strings.HasSuffix(name, "(int)") || strings.HasSuffix(name, "(integer)") {
			name = strings.Split(name, "(")[0]
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "integer",
				"description": field.Description,
			}
		} else if strings.HasSuffix(name, "(float)") || strings.HasSuffix(name, "(number)") {
			name = strings.Split(name, "(")[0]
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "number",
				"description": field.Description,
			}
		} else if strings.HasSuffix(name, "(bool)") || strings.HasSuffix(name, "(boolean)") {
			name = strings.Split(name, "(")[0]
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "boolean",
				"description": field.Description,
			}
		} else if enumSyntaxRegexp.MatchString(name) {
			name, args, _ := strings.Cut(name, "(")
			var (
				enum []string
			)
			for arg := range strings.SplitSeq(strings.TrimSuffix(args, ")"), ",") {
				enum = append(enum, strings.TrimSpace(arg))
			}
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "string",
				"description": field.Description,
				"enum":        enum,
			}
		} else if len(field.Fields) > 0 {
			jsonschema["properties"].(map[string]any)[name] = buildSimpleSchema("", field.Description, field.Fields)
		} else {
			jsonschema["properties"].(map[string]any)[name] = map[string]any{
				"type":        "string",
				"description": field.Description,
			}
		}

		if field.Required == nil || *field.Required {
			required = append(required, name)
		}
	}

	jsonschema["required"] = required
	return jsonschema
}
