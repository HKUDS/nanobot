package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"net/url"
	"slices"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/expr"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/runtime"
	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/nanobot-ai/nanobot/pkg/sessiondata"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type Server struct {
	handlers           []handler
	runtime            *runtime.Runtime
	data               *sessiondata.Data
	config             types.ConfigFactory
	manager            *session.Manager
	forceFetchToolList bool
}

type Options struct {
	ForceFetchToolList bool
}

func (o Options) Merge(other Options) Options {
	return Options{
		ForceFetchToolList: o.ForceFetchToolList || other.ForceFetchToolList,
	}
}

func NewServer(runtime *runtime.Runtime, config types.ConfigFactory, manager *session.Manager, options ...Options) *Server {
	opt := complete.Complete(options...)
	s := &Server{
		runtime:            runtime,
		data:               sessiondata.NewData(runtime),
		config:             config,
		manager:            manager,
		forceFetchToolList: opt.ForceFetchToolList,
	}
	s.init()
	return s
}

type handler func(ctx context.Context, msg mcp.Message) (bool, error)

func handle[T any](method string, handler func(ctx context.Context, req mcp.Message, payload T) error) handler {
	return func(ctx context.Context, msg mcp.Message) (bool, error) {
		if msg.Method != method {
			return false, nil
		}
		var payload T
		if len(msg.Params) > 0 && !bytes.Equal(msg.Params, []byte("null")) {
			if err := json.Unmarshal(msg.Params, &payload); err != nil {
				return false, err
			}
		}
		return true, handler(ctx, msg, payload)
	}
}

func (s *Server) init() {
	s.handlers = []handler{
		handle("initialize", s.handleInitialize),
		handle("notifications/initialized", s.handleInitialized),
		handle("ping", s.handlePing),
		handle("logging/setLevel", s.handleSetLogLevel),
		handle("tools/list", s.handleListTools),
		handle("tools/call", s.handleCallTool),
		handle("prompts/list", s.handleListPrompts),
		handle("prompts/get", s.handleGetPrompt),
		handle("resources/templates/list", s.handleListResourceTemplates),
		handle("resources/list", s.handleListResources),
		handle("resources/read", s.handleReadResource),
		handle("resources/subscribe", s.handleResourcesSubscribe),
		handle("resources/unsubscribe", s.handleResourcesUnsubscribe),
		handle("notifications/cancelled", s.handleCancelled),
	}
}

func (s *Server) handleResourcesUnsubscribe(ctx context.Context, msg mcp.Message, payload mcp.UnsubscribeRequest) error {
	err := s.data.UnsubscribeFromResources(ctx, payload.URI)
	if err != nil {
		return err
	}
	return msg.Reply(ctx, map[string]any{})
}

func (s *Server) handleResourcesSubscribe(ctx context.Context, msg mcp.Message, payload mcp.SubscribeRequest) error {
	err := s.data.SubscribeToResources(ctx, payload.URI)
	if err != nil {
		return err
	}
	return msg.Reply(ctx, map[string]any{})
}

func (s *Server) handleListResourceTemplates(ctx context.Context, msg mcp.Message, _ mcp.ListResourceTemplatesRequest) error {
	resourceTemplateMappings, err := s.data.PublishedResourceTemplateMappings(ctx)
	if err != nil {
		return err
	}

	result := mcp.ListResourceTemplatesResult{
		ResourceTemplates: []mcp.ResourceTemplate{},
	}

	for _, k := range slices.Sorted(maps.Keys(resourceTemplateMappings)) {
		match := resourceTemplateMappings[k].Target
		result.ResourceTemplates = append(result.ResourceTemplates, match.ResourceTemplate)
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handleReadResource(ctx context.Context, msg mcp.Message, payload mcp.ReadResourceRequest) error {
	target, resourceName, err := s.data.MatchPublishedResource(ctx, payload.URI)
	if err != nil {
		return fmt.Errorf("failed to read resource %s: %v", payload.URI, err)
	}

	c, err := s.runtime.GetClient(ctx, target)
	if err != nil {
		return fmt.Errorf("failed to get client for server %s: %w", target, err)
	}

	result, err := c.ReadResource(ctx, resourceName)
	if err != nil {
		return err
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handleGetPrompt(ctx context.Context, msg mcp.Message, payload mcp.GetPromptRequest) error {
	promptMappings, err := s.data.PublishedPromptMappings(ctx)
	if err != nil {
		return err
	}

	promptMapping, ok := promptMappings[payload.Name]
	if !ok {
		return fmt.Errorf("prompt %s not found", payload.Name)
	}

	result, err := s.runtime.GetPrompt(ctx, promptMapping.MCPServer, promptMapping.TargetName, payload.Arguments)
	if err != nil {
		return err
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handleListResources(ctx context.Context, msg mcp.Message, _ mcp.ListResourcesRequest) error {
	resourceMappings, err := s.data.PublishedResourceMappings(ctx)
	if err != nil {
		return err
	}

	result := mcp.ListResourcesResult{
		Resources: []mcp.Resource{},
	}

	for _, k := range slices.Sorted(maps.Keys(resourceMappings)) {
		result.Resources = append(result.Resources, resourceMappings[k].Target)
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handleListPrompts(ctx context.Context, msg mcp.Message, _ mcp.ListPromptsRequest) error {
	s.data.Refresh(ctx, false)
	promptMappings, err := s.data.PublishedPromptMappings(ctx)
	if err != nil {
		return err
	}

	result := mcp.ListPromptsResult{
		Prompts: []mcp.Prompt{},
	}

	for _, k := range slices.Sorted(maps.Keys(promptMappings)) {
		result.Prompts = append(result.Prompts, promptMappings[k].Target)
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handleCallTool(ctx context.Context, msg mcp.Message, payload mcp.CallToolRequest) error {
	start := time.Now()

	toolMappings, err := s.data.ToolMapping(ctx)
	if err != nil {
		return err
	}

	toolMapping, ok := toolMappings[payload.Name]
	if !ok {
		s.data.Refresh(ctx, false)
		toolMappings, err = s.data.ToolMapping(ctx)
		if err != nil {
			return err
		}
		toolMapping, ok = toolMappings[payload.Name]
		if !ok {
			return fmt.Errorf("tool %s not found", payload.Name)
		}
	}

	slog.Debug("mcp server dispatching tool call",
		"mcp_tool_name", payload.Name,
		"target_server", toolMapping.MCPServer,
		"target_tool_name", toolMapping.TargetName,
		"request_id", mcp.MessageIDString(msg.ID))

	result, err := s.runtime.Call(ctx, toolMapping.MCPServer, toolMapping.TargetName, payload.Arguments, tools.CallOptions{
		ProgressToken: msg.ProgressToken(),
		LogData: map[string]any{
			"mcpToolName": payload.Name,
		},
		Meta: msg.Meta(),
	})
	if err != nil {
		return err
	}
	slog.Debug("mcp server completed tool call",
		"mcp_tool_name", payload.Name,
		"target_server", toolMapping.MCPServer,
		"target_tool_name", toolMapping.TargetName,
		"request_id", mcp.MessageIDString(msg.ID),
		"is_error", result.IsError,
		"duration_ms", time.Since(start).Milliseconds())
	mcpResult := mcp.CallToolResult{
		StructuredContent: result.StructuredContent,
		IsError:           result.IsError,
		Content:           result.Content,
	}

	return msg.Reply(ctx, mcpResult)
}

func (s *Server) handleListTools(ctx context.Context, msg mcp.Message, _ mcp.ListToolsRequest) error {
	result := mcp.ListToolsResult{
		Tools: []mcp.Tool{},
	}

	toolMappings, err := s.data.ToolMapping(ctx, sessiondata.GetOption{ForceFetch: s.forceFetchToolList})
	if err != nil {
		return err
	}

	for _, k := range slices.Sorted(maps.Keys(toolMappings)) {
		result.Tools = append(result.Tools, toolMappings[k].Target.Tool)
	}

	return msg.Reply(ctx, result)
}

func (s *Server) handlePing(ctx context.Context, msg mcp.Message, _ struct{}) error {
	return msg.Reply(ctx, mcp.PingResult{})
}

func getEnvVal(envMap map[string]string, envKey string, envDef types.EnvDef) string {
	val, ok := expr.Lookup(envMap, envKey)
	if ok {
		return val
	}

	if envDef.UseBearerToken {
		bearer, ok := envMap["http:bearer-token"]
		if ok && bearer != "" {
			return bearer
		}
	}

	if !envDef.Optional {
		return ""
	}

	return envDef.Default
}

func reconcileEnv(session *mcp.Session, c types.Config) error {
	envMap := session.GetEnvMap()
	var missing []string
	for envKey, envDef := range c.Env {
		envVal := getEnvVal(envMap, envKey, envDef)
		if envVal == "" && !envDef.Optional {
			missing = append(missing, envKey)
			continue
		}
		envMap[envKey] = envVal
	}

	if len(missing) == 0 {
		return nil
	}

	var missingEnv []any
	for _, key := range missing {
		values := map[string]any{
			"name":        key,
			"description": c.Env[key].Description,
			"default":     c.Env[key].Default,
		}
		if len(c.Env[key].Options) > 0 {
			values["options"] = c.Env[key].Options
		}
		missingEnv = append(missingEnv, values)
	}
	return &mcp.RPCError{
		Code:    -32602,
		Message: fmt.Sprintf("missing required environment variables: %v", missing),
		DataObject: map[string]any{
			"missingEnv": missingEnv,
		},
	}
}

func (s *Server) handleInitialized(ctx context.Context, msg mcp.Message, payload mcp.Notification) error {
	return nil
}

func (s *Server) initUI(params types.SessionInitHook) types.SessionInitHook {
	if _, ok := params.Meta["ui"]; ok {
		return params
	}
	if _, ok := params.Meta["chat"]; ok {
		return params
	}

	u, err := url.Parse(params.URL)
	if err != nil {
		// ignore parsing error
		return params
	}

	if params.Meta == nil {
		params.Meta = make(map[string]any)
	}
	params.Meta["ui"] = u.Path == "/mcp/ui"
	params.Meta["chat"] = u.Path == "/mcp/chat"
	return params
}

func (s *Server) runInitHook(ctx context.Context) (types.SessionInitHook, error) {
	var (
		sessionInit types.SessionInitHook
		session     = mcp.SessionFromContext(ctx)
		c           = types.ConfigFromContext(ctx)
		req         = mcp.RequestFromContext(ctx)
	)

	session.Get(types.SessionInitSessionKey, &sessionInit)
	sessionInit.SessionID = session.ID()
	if req != nil {
		sessionInit.URL = sessiondata.GetHostURL(req)
	}

	sessionInit = s.initUI(sessionInit)

	sessionInit, err := mcp.InvokeHooks(ctx, s.runtime, c.Hooks, &sessionInit, "session", nil)
	if err != nil {
		return sessionInit, fmt.Errorf("failed to invoke session hook: %w", err)
	}

	session.Set(types.SessionInitSessionKey, &sessionInit)
	return sessionInit, nil
}

func (s *Server) handleInitialize(ctx context.Context, msg mcp.Message, payload mcp.InitializeRequest) error {
	sessionInit, err := s.runInitHook(ctx)
	if err != nil {
		return err
	}

	session := mcp.SessionFromContext(ctx)
	c := types.ConfigFromContext(ctx)

	if err := reconcileEnv(session, c); err != nil {
		return err
	}

	s.data.Refresh(ctx, false)

	experimental := map[string]any{}
	meta := map[string]any{}
	if len(sessionInit.Meta) > 0 {
		meta["session"] = sessionInit.Meta
	}

	if c.Publish.Introduction.IsSet() {
		intro, err := s.runtime.GetDynamicInstruction(ctx, c.Publish.Introduction)
		if err != nil {
			return fmt.Errorf("failed to get introduction: %w", err)
		}
		meta["intro"] = intro
	}
	if len(meta) > 0 {
		experimental[types.MetaNanobot] = meta
	}

	if c.Publish.IsSingleServerProxy() {
		// This nanobot just exposes a single MCP server. Call the initialize directly and return its response.
		c, err := s.data.InitializedClient(ctx, c.Publish.MCPServers[0])
		if err != nil {
			return fmt.Errorf("failed to initialize client: %w", err)
		}

		return msg.Reply(ctx, c.Session.InitializeResult)
	}

	return msg.Reply(ctx, mcp.InitializeResult{
		ProtocolVersion: payload.ProtocolVersion,
		Capabilities: mcp.ServerCapabilities{
			Experimental: experimental,
			Logging:      &struct{}{},
			Prompts:      &mcp.PromptsServerCapability{},
			Resources: &mcp.ResourcesServerCapability{
				Subscribe:   true,
				ListChanged: true,
			},
			Tools: &mcp.ToolsServerCapability{},
		},
		ServerInfo: mcp.ServerInfo{
			Name:    c.Publish.Name,
			Version: c.Publish.Version,
		},
		Instructions: c.Publish.Instructions,
	})
}

func (s *Server) handleSetLogLevel(ctx context.Context, msg mcp.Message, payload mcp.SetLogLevelRequest) error {
	config := types.ConfigFromContext(ctx)

	// Iterate through all MCP servers and set their log level
	for serverName := range config.MCPServers {
		c, err := s.runtime.GetClient(ctx, serverName)
		if err != nil {
			return fmt.Errorf("failed to get client for %s: %w", serverName, err)
		}

		if err := c.SetLogLevel(ctx, payload.Level); err != nil {
			return fmt.Errorf("failed to set log level for %s: %w", serverName, err)
		}
	}

	return msg.Reply(ctx, mcp.SetLogLevelResult{})
}

func (s *Server) handleCancelled(ctx context.Context, msg mcp.Message, payload mcp.CancelledNotification) error {
	mcp.SessionFromContext(ctx).StopAllFromRequestID(payload.RequestID, new(payload.Reason))

	// No response for notifications
	return nil
}

func (s *Server) OnMessage(ctx context.Context, msg mcp.Message) {
	if msg.ID != nil {
		ctx = mcp.WithRequestID(ctx, msg.ID)
	}

	msg.Session.Run(ctx, msg, func(ctx context.Context, m mcp.Message) {
		s.onMessage(ctx, m)
	})
}

func (s *Server) onMessage(ctx context.Context, msg mcp.Message) {
	if err := s.data.Sync(ctx, s.config); err != nil {
		msg.SendError(ctx, err)
		return
	}

	mcp.SessionFromContext(ctx).Set(session.ManagerSessionKey, s.manager)

	for _, h := range s.handlers {
		ok, err := h(ctx, msg)
		if err != nil {
			// Check if the error was due to client-initiated cancellation
			if cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](context.Cause(mcp.UserContext(ctx))); ok {
				// Send a proper cancellation error response
				msg.SendError(ctx, mcp.ErrRPCRequestCancelled.WithMessage("%s", cancelErr.Reason))
			} else {
				msg.SendError(ctx, err)
			}
			return
		} else if ok {
			return
		}
	}

	msg.SendError(ctx, mcp.ErrRPCMethodNotFound.WithMessage("%s", msg.Method))
}
