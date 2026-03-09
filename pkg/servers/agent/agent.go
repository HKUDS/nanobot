package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/nanobot-ai/nanobot/pkg/agents"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/sampling"
	"github.com/nanobot-ai/nanobot/pkg/sessiondata"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/version"
)

type Server struct {
	tools      mcp.ServerTools
	data       *sessiondata.Data
	agentName  string
	agents     *agents.Agents
	multiAgent bool
	runtime    Caller
}

type Caller interface {
	Call(ctx context.Context, server, tool string, args any, opts ...tools.CallOptions) (ret *types.CallResult, err error)
	GetClient(ctx context.Context, name string) (*mcp.Client, error)
	GetPrompt(ctx context.Context, target, prompt string, args map[string]string) (*mcp.GetPromptResult, error)
}

func NewServer(d *sessiondata.Data, r Caller, agents *agents.Agents, name string) *Server {
	s := &Server{
		data:      d,
		agentName: name,
		agents:    agents,
		runtime:   r,
	}

	s.tools = mcp.NewServerTools(
		chatCall{s: s},
	)

	return s
}

func (s *Server) withConfig(ctx context.Context) (context.Context, error) {
	newConfig, err := s.agents.GetConfigForAgent(ctx, s.agentName)
	if err != nil {
		return ctx, err
	}
	return types.WithConfig(ctx, newConfig), nil
}

func (s *Server) OnMessage(ctx context.Context, msg mcp.Message) {
	switch msg.Method {
	case "initialize":
		mcp.Invoke(ctx, msg, s.initialize)
		return
	case "notifications/initialized":
		// nothing to do
		return
	case "notifications/cancelled":
		mcp.HandleCancelled(ctx, msg)
		return
	case "tools/list":
		mcp.Invoke(ctx, msg, s.tools.List)
		return
	case "tools/call":
		mcp.Invoke(ctx, msg, s.tools.Call)
		return
	case "resources/read":
		mcp.Invoke(ctx, msg, s.resourcesRead)
		return
	case "resources/subscribe":
		msg.Reply(ctx, &mcp.SubscribeResult{})
		return
	case "resources/unsubscribe":
		msg.Reply(ctx, &mcp.UnsubscribeResult{})
		return
	}

	ctx, err := s.withConfig(ctx)
	if err != nil {
		msg.SendError(ctx, err)
		return
	}

	switch msg.Method {
	case "resources/list":
		mcp.Invoke(ctx, msg, s.resourcesList)
	case "resources/templates/list":
		mcp.Invoke(ctx, msg, s.resourcesTemplatesList)
	case "prompts/list":
		mcp.Invoke(ctx, msg, s.promptsList)
	case "prompts/get":
		mcp.Invoke(ctx, msg, s.promptGet)
	default:
		msg.SendError(ctx, mcp.ErrRPCMethodNotFound.WithMessage("%v", msg.Method))
	}
}

func messagesToResourceContents(messages []types.Message) ([]mcp.ResourceContent, error) {
	var contents []mcp.ResourceContent
	for _, msg := range messages {
		data, err := json.Marshal(msg)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal message: %w", err)
		}
		contents = append(contents, mcp.ResourceContent{
			URI:      fmt.Sprintf(types.MessageURI, msg.ID),
			MIMEType: types.MessageMimeType,
			Text:     &[]string{string(data)}[0],
		})
	}
	return contents, nil
}

func (s *Server) readHistory(ctx context.Context) (ret []mcp.ResourceContent, _ error) {
	messages, err := GetMessages(ctx)
	if err != nil {
		return nil, err
	}
	return messagesToResourceContents(messages)
}

func (s *Server) readProgress(ctx context.Context) (ret []mcp.ResourceContent, _ error) {
	var (
		progress types.CompletionResponse
		session  = mcp.SessionFromContext(ctx)
	)

	if !session.Get("progress", &progress) {
		return nil, nil
	}

	callResult, err := sampling.CompletionResponseToCallResult(&progress, true, nil)
	if err != nil {
		return nil, err
	}

	data, err := json.Marshal(types.AsyncCallResult{
		IsError:       callResult.IsError,
		Content:       callResult.Content,
		InProgress:    progress.HasMore,
		ToolName:      types.AgentTool + callResult.Agent,
		ProgressToken: progress.ProgressToken,
	})
	if err != nil {
		return nil, err
	}

	result := []mcp.ResourceContent{
		{
			URI:      types.ProgressURI,
			MIMEType: types.ToolResultMimeType,
			Text:     &[]string{string(data)}[0],
		},
	}
	for _, content := range callResult.Content {
		if content.Resource != nil && content.Resource.MIMEType == types.MessageMimeType {
			result = append(result, mcp.ResourceContent{
				URI:      content.Resource.URI,
				Name:     content.Name,
				MIMEType: content.Resource.MIMEType,
				Text:     &content.Resource.Text,
			})
		}
	}

	return result, nil
}

func (s *Server) readPendingElicitation(ctx context.Context) ([]mcp.ResourceContent, error) {
	var pending PendingElicitation
	session := mcp.SessionFromContext(ctx)
	if !session.Get(pendingElicitationKey, &pending) {
		return nil, nil
	}

	data, err := json.Marshal(pending)
	if err != nil {
		return nil, err
	}

	return []mcp.ResourceContent{
		{
			URI:      types.ElicitationURI,
			MIMEType: types.ElicitationMimeType,
			Text:     &[]string{string(data)}[0],
		},
	}, nil
}

func (s *Server) promptGet(ctx context.Context, _ mcp.Message, payload mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
	c := types.ConfigFromContext(ctx)
	agent := c.Agents[s.agentName]

	promptMappings, err := s.data.BuildPromptMappings(ctx, slices.Concat(agent.MCPServers, agent.Prompts))
	if err != nil {
		return nil, err
	}

	promptMapping, ok := promptMappings[payload.Name]
	if !ok {
		return nil, fmt.Errorf("prompt %s not found", payload.Name)
	}

	return s.runtime.GetPrompt(ctx, promptMapping.MCPServer, promptMapping.TargetName, payload.Arguments)
}

func (s *Server) promptsList(ctx context.Context, _ mcp.Message, _ mcp.ListPromptsRequest) (*mcp.ListPromptsResult, error) {
	c := types.ConfigFromContext(ctx)
	agent := c.Agents[s.agentName]
	result := &mcp.ListPromptsResult{}

	prompts, err := s.data.BuildPromptMappings(ctx, slices.Concat(agent.MCPServers, agent.Prompts))
	if err != nil {
		return nil, err
	}

	for _, prompt := range prompts {
		result.Prompts = append(result.Prompts, prompt.Target)
	}

	return result, nil
}

func (s *Server) resourcesRead(ctx context.Context, _ mcp.Message, request mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
	var (
		contents []mcp.ResourceContent
		err      error
	)

	switch request.URI {
	case types.HistoryURI:
		contents, err = s.readHistory(ctx)
		if err != nil {
			return nil, err
		}
		return &mcp.ReadResourceResult{
			Contents: contents,
		}, nil
	case types.ProgressURI:
		contents, err = s.readProgress(ctx)
		if err != nil {
			return nil, err
		}
		return &mcp.ReadResourceResult{
			Contents: contents,
		}, nil
	case types.ElicitationURI:
		contents, err = s.readPendingElicitation(ctx)
		if err != nil {
			return nil, err
		}
		return &mcp.ReadResourceResult{
			Contents: contents,
		}, nil
	}

	ctx, err = s.withConfig(ctx)
	if err != nil {
		return nil, err
	}

	c := types.ConfigFromContext(ctx)
	agent := c.Agents[s.agentName]

	server, resourceName, err := s.data.MatchResource(ctx, request.URI, slices.Concat(agent.MCPServers, agent.Resources))
	if err != nil {
		return nil, err
	}

	client, err := s.runtime.GetClient(ctx, server)
	if err != nil {
		return nil, err
	}

	return client.ReadResource(ctx, resourceName)
}

func (s *Server) resourcesTemplatesList(ctx context.Context, _ mcp.Message, _ mcp.ListResourcesRequest) (*mcp.ListResourceTemplatesResult, error) {
	c := types.ConfigFromContext(ctx)
	agent := c.Agents[s.agentName]
	result := &mcp.ListResourceTemplatesResult{}

	resources, err := s.data.BuildResourceTemplateMappings(ctx, slices.Concat(agent.MCPServers, agent.Resources))
	if err != nil {
		return nil, err
	}

	for _, resource := range resources {
		result.ResourceTemplates = append(result.ResourceTemplates, resource.Target.ResourceTemplate)
	}

	return result, nil
}

func (s *Server) resourcesList(ctx context.Context, _ mcp.Message, _ mcp.ListResourcesRequest) (*mcp.ListResourcesResult, error) {
	c := types.ConfigFromContext(ctx)
	agent := c.Agents[s.agentName]
	result := &mcp.ListResourcesResult{}

	resources, err := s.data.BuildResourceMappings(ctx, slices.Concat(agent.MCPServers, agent.Resources))
	if err != nil {
		return nil, err
	}

	for _, resource := range resources {
		result.Resources = append(result.Resources, resource.Target)
	}

	result.Resources = append(result.Resources, mcp.Resource{
		URI:         types.HistoryURI,
		Name:        "chat-history",
		Title:       "Chat History",
		Description: "The chat history for the current agent.",
		MimeType:    types.HistoryMimeType,
	}, mcp.Resource{
		URI:         types.ProgressURI,
		Name:        "chat-progress",
		Title:       "Chat Streaming Progress",
		Description: "The streaming content of the current or last chat exchange.",
		MimeType:    types.ToolResultMimeType,
	}, mcp.Resource{
		URI:         types.ElicitationURI,
		Name:        "pending-elicitation",
		Title:       "Pending Elicitation",
		Description: "The pending elicitation for the current session, if any.",
		MimeType:    types.ElicitationMimeType,
	})
	return result, nil
}

func (s *Server) initialize(_ context.Context, _ mcp.Message, params mcp.InitializeRequest) (*mcp.InitializeResult, error) {
	return &mcp.InitializeResult{
		ProtocolVersion: params.ProtocolVersion,
		Capabilities: mcp.ServerCapabilities{
			Tools:     &mcp.ToolsServerCapability{},
			Prompts:   &mcp.PromptsServerCapability{},
			Resources: &mcp.ResourcesServerCapability{},
		},
		ServerInfo: mcp.ServerInfo{
			Name:    version.Name,
			Version: version.Get().String(),
		},
	}, nil
}
