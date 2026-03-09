package agents

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strings"
	"time"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/llm/progress"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/schema"
	"github.com/nanobot-ai/nanobot/pkg/sessiondata"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

type Agents struct {
	completer types.Completer
	registry  *tools.Service
}

type ToolListOptions struct {
	ToolName string
	Names    []string
}

func New(completer types.Completer, registry *tools.Service) *Agents {
	return &Agents{
		completer: completer,
		registry:  registry,
	}
}

func (a *Agents) addTools(ctx context.Context, req *types.CompletionRequest, agent *types.Agent, opts []types.CompletionOptions) (types.ToolMappings, error) {
	opt := complete.Complete(opts...)

	if opt.ToolChoice != nil {
		switch opt.ToolChoice.Mode {
		case "none":
			req.ToolChoice = "none"
		case "auto":
			req.ToolChoice = "auto"
		case "required":
			req.ToolChoice = "required"
		}
	}

	toolMappings, err := a.registry.BuildToolMappings(ctx, slices.Concat(agent.Tools, agent.Agents, agent.MCPServers))
	if err != nil {
		return nil, fmt.Errorf("failed to build tool mappings: %w", err)
	}

	switch opt.ToolIncludeContext {
	case "none":
		toolMappings = types.ToolMappings{}
	case "thisServer":
		newMappings := types.ToolMappings{}
		for key, mapping := range toolMappings {
			if mapping.MCPServer == opt.ToolSource {
				newMappings[key] = mapping
			}
		}
		toolMappings = newMappings
	}

	for _, key := range slices.Sorted(maps.Keys(toolMappings)) {
		toolMapping := toolMappings[key]

		tool := toolMapping.Target
		if !types.IsModelTool(tool.Tool) {
			continue
		}
		req.Tools = append(req.Tools, types.ToolUseDefinition{
			Name:        key,
			Parameters:  schema.ValidateAndFixToolSchema(tool.InputSchema),
			Description: tool.Description,
			Attributes:  agent.ToolExtensions[toolMapping.Target.Name],
		})
	}

	for _, tool := range opt.Tools {
		toolMappings[tool.Name] = types.TargetMapping[types.TargetTool]{
			Target: types.TargetTool{
				Tool:     tool,
				External: true,
			},
		}
		req.Tools = append(req.Tools, types.ToolUseDefinition{
			Name:        tool.Name,
			Parameters:  schema.ValidateAndFixToolSchema(tool.InputSchema),
			Description: tool.Description,
		})
	}

	return toolMappings, nil
}

func (a *Agents) populateRequest(ctx context.Context, config types.Config, run *types.Execution, previousRun *types.Execution, opts []types.CompletionOptions) (types.CompletionRequest, types.ToolMappings, error) {
	req := run.Request

	if previousRun != nil {
		input := previousRun.PopulatedRequest.Input

		for _, outputMessage := range append(previousRun.Response.InternalMessages, previousRun.Response.Output) {
			newItems := make([]types.CompletionItem, 0, len(outputMessage.Items))
			for _, output := range outputMessage.Items {
				prevInput := output
				if prevInput.ToolCall != nil {
					// We are skipping invalid tool calls that point have no corresponding tool output
					if _, exists := previousRun.ToolOutputs[prevInput.ToolCall.CallID]; !exists {
						continue
					}
				}
				newItems = append(newItems, prevInput)
			}

			if len(newItems) > 0 {
				outputMessage.Items = newItems
				input = append(input, outputMessage)
			}
		}

		for _, callID := range slices.Sorted(maps.Keys(previousRun.ToolOutputs)) {
			toolCall := previousRun.ToolOutputs[callID]
			if toolCall.Done {
				input = append(input, toolCall.Output)
			}
		}

		input = append(input, req.Input...)
		req.Input = input
	}

	agentName := req.GetAgent()

	agent, ok := config.Agents[agentName]
	if !ok {
		return req, nil, nil
	}

	req.Agent = agentName
	req.Reasoning = agent.Reasoning

	if req.SystemPrompt != "" {
		var agentInstructions types.DynamicInstructions
		if err := json.Unmarshal([]byte(strings.TrimSpace(req.SystemPrompt)), &agentInstructions); err == nil &&
			agentInstructions.IsPrompt() {
			req.SystemPrompt = ""
			agent.Instructions = agentInstructions
		}
	}

	if req.SystemPrompt == "" && agent.Instructions.IsSet() {
		var err error
		req.SystemPrompt, err = a.registry.GetDynamicInstruction(ctx, agent.Instructions)
		if err != nil {
			return req, nil, err
		}
	}

	if req.TopP == nil && agent.TopP != nil {
		req.TopP = agent.TopP
	}

	if req.Temperature == nil && agent.Temperature != nil {
		req.Temperature = agent.Temperature
	}

	if req.Truncation == "" && agent.Truncation != "" {
		req.Truncation = agent.Truncation
	}

	if req.MaxTokens == 0 && agent.MaxTokens != 0 {
		req.MaxTokens = agent.MaxTokens
	}

	if req.ToolChoice == "" && agent.ToolChoice != "" {
		req.ToolChoice = agent.ToolChoice
	}

	if previousRun != nil {
		// Don't allow tool choice if this is a follow-on request
		req.ToolChoice = ""
	}

	if req.OutputSchema == nil && agent.Output != nil && len(agent.Output.ToSchema()) > 0 {
		req.OutputSchema = &types.OutputSchema{
			Name:        agent.Output.Name,
			Description: agent.Output.Description,
			Schema:      agent.Output.ToSchema(),
			Strict:      agent.Output.Strict,
		}
	}

	if req.OutputSchema != nil && req.OutputSchema.Name == "" {
		req.OutputSchema.Name = "output_schema"
	}

	if req.ThreadName == "" {
		req.ThreadName = agent.ThreadName
	}

	req.Model = agent.Model

	toolMapping, err := a.addTools(ctx, &req, &agent, opts)
	if err != nil {
		return req, nil, fmt.Errorf("failed to add tools: %w", err)
	}

	// Validate and fix tool input schemas
	for i, tool := range req.Tools {
		fixedSchema := schema.ValidateAndFixToolSchema(tool.Parameters)
		req.Tools[i].Parameters = fixedSchema
	}

	return req, toolMapping, nil
}

func (a *Agents) replacePrompt(ctx context.Context, agentConfig types.Agent, items []types.CompletionItem) (result []types.CompletionItem, messages []mcp.PromptMessage, err error) {
	if len(items) != 1 || items[0].Content == nil || items[0].Content.Type != "text" {
		return items, nil, nil
	}

	var uiAction types.UIAction
	if err := json.Unmarshal([]byte(items[0].Content.Text), &uiAction); err != nil {
		// Ignore invalid JSON
		return items, nil, nil
	}

	if uiAction.Prompt != nil && uiAction.Prompt.Prompt != "" {
		newItem := items[0]
		newItem.Content = &mcp.Content{
			Type: "text",
			Text: uiAction.Prompt.Prompt,
		}
		return []types.CompletionItem{newItem}, nil, nil
	} else if uiAction.Prompt != nil && len(uiAction.Prompt.RenderedMessages) > 0 {
		return items, uiAction.Prompt.RenderedMessages, nil
	} else if uiAction.Prompt != nil && uiAction.Prompt.PromptName != "" {
		prompts, err := sessiondata.NewData(a.registry).BuildPromptMappings(ctx, slices.Concat(agentConfig.MCPServers, agentConfig.Prompts))
		if err != nil {
			return items, nil, nil
		}
		prompt, ok := prompts[uiAction.Prompt.PromptName]
		if !ok {
			return nil, nil, fmt.Errorf("prompt %q not found", uiAction.Prompt.PromptName)
		}

		messages, err := a.registry.GetPrompt(ctx, prompt.MCPServer, prompt.TargetName, uiAction.Prompt.Params)
		if err != nil {
			return items, nil, err
		}

		uiAction.Prompt.RenderedMessages = messages.Messages
		newText, err := json.Marshal(uiAction)
		if err != nil {
			return items, nil, fmt.Errorf("failed to marshal UIAction: %w", err)
		}

		// purposefully modify the original message so it gets saved, so we don't call on each turn
		items[0].Content.Text = string(newText)

		return items, messages.Messages, err
	}

	return items, nil, nil
}

func (a *Agents) handleUIAction(ctx context.Context, config types.Config, req types.CompletionRequest, opts []types.CompletionOptions) (types.CompletionRequest, *types.CompletionResponse, error) {
	var (
		uiAction    types.UIAction
		err         error
		lastMessage types.Message
		opt         = complete.Complete(opts...)
	)

	if len(req.Input) == 0 {
		return req, nil, nil
	}

	// copy
	newReq := req
	newReq.Input = nil
	for _, msg := range req.Input {
		if msg.Role != "user" {
			newReq.Input = append(newReq.Input, msg)
			continue
		}
		newItems, promptMessages, err := a.replacePrompt(ctx, config.Agents[req.Agent], msg.Items)
		if err != nil {
			return req, nil, fmt.Errorf("failed to replace prompt: %w", err)
		}
		if len(promptMessages) > 0 {
			for i, promptMessage := range promptMessages {
				newMessage := types.Message{
					ID:      fmt.Sprintf("%s-prompt-%d", msg.ID, i),
					Created: msg.Created,
					Role:    promptMessage.Role,
					Items: []types.CompletionItem{
						{
							ID:      fmt.Sprintf("%s-prompt-item-%d", msg.ID, i),
							Content: &promptMessage.Content,
						},
					},
				}
				if newMessage.Role == "" {
					newMessage.Role = "user"
				}
				// Reset id's for first element to match original message id
				if i == 0 {
					newMessage.ID = msg.ID
					if len(msg.Items) == 1 {
						newMessage.Items[0].ID = msg.Items[0].ID
					}
				}

				newReq.Input = append(newReq.Input, newMessage)
			}
		} else {
			msg.Items = newItems
			newReq.Input = append(newReq.Input, msg)
		}

	}

	lastMessage = newReq.Input[len(req.Input)-1]
	if lastMessage.Role != "user" {
		return newReq, nil, nil
	}

	if len(lastMessage.Items) != 1 || lastMessage.Items[0].Content == nil || lastMessage.Items[0].Content.Type != "text" {
		return newReq, nil, nil
	}

	if err := json.Unmarshal([]byte(lastMessage.Items[0].Content.Text), &uiAction); err != nil {
		// Ignore invalid JSON
		return newReq, nil, nil
	}

	if uiAction.Tool != nil && uiAction.Tool.ToolName != "" {
		args := []byte("{}")
		if len(uiAction.Tool.Params) > 0 {
			args, err = json.Marshal(uiAction.Tool.Params)
			if err != nil {
				return newReq, nil, err
			}
		}
		resp := &types.CompletionResponse{
			Output: types.Message{
				ID:   uuid.String(),
				Role: "assistant",
				Items: []types.CompletionItem{
					{
						ID: "fc_" + uuid.String(),
						ToolCall: &types.ToolCall{
							Arguments: string(args),
							CallID:    uuid.String(),
							Name:      uiAction.Tool.ToolName,
						},
					},
				},
			},
		}

		progress.Send(ctx, &types.CompletionProgress{
			MessageID: resp.Output.ID,
			Role:      "assistant",
			Item:      resp.Output.Items[0],
		}, opt.ProgressToken)

		return newReq, resp, nil
	}

	return newReq, nil, nil
}

func (a *Agents) Complete(ctx context.Context, req types.CompletionRequest, opts ...types.CompletionOptions) (_ *types.CompletionResponse, err error) {
	var (
		previousExecutionKey = types.PreviousExecutionKey
		session              = mcp.SessionFromContext(ctx)
		isChat               = session != nil
		previousRun          *types.Execution
		currentRun           = &types.Execution{}
		baseConfig           = types.ConfigFromContext(ctx)
		startID              = ""
	)

	for session != nil && session.Parent != nil {
		session = session.Parent
	}

	if len(req.Input) > 0 {
		startID = req.Input[0].ID
		if startID == "" {
			startID = uuid.String()
			req.Input[0].ID = startID
		}
	}

	if req.ThreadName != "" {
		previousExecutionKey = fmt.Sprintf("%s/%s", previousExecutionKey, req.ThreadName)
	}

	if isChat && baseConfig.Agents[req.Model].Chat != nil && !*baseConfig.Agents[req.Model].Chat {
		isChat = false
	}

	if ch := complete.Complete(opts...).Chat; ch != nil {
		isChat = *ch
	}

	// Save the original request to the Execution status
	currentRun.Request = req

	if isChat {
		var fallBack *types.Execution
		if lookup := (types.Execution{}); session.Get(previousExecutionKey, &lookup) {
			fallBack = &lookup
			previousRun = &lookup
		}

		if req.NewThread && previousRun != nil {
			session.Set(previousExecutionKey+"/"+time.Now().Format(time.RFC3339), previousRun)
			session.Set(previousExecutionKey, nil)
		}

		defer func() {
			if err != nil && fallBack != nil {
				session.Set(previousExecutionKey, fallBack)
			}
		}()
	}

	for {
		config, err := a.configHook(ctx, baseConfig, currentRun.Request.GetAgent())
		if err != nil {
			return nil, err
		}

		ctx := types.WithConfig(ctx, config)

		if err := a.run(ctx, config, currentRun, previousRun, opts); err != nil {
			return nil, err
		}

		if isChat {
			session.Set(previousExecutionKey, currentRun)
		}

		// This doesn't return an error because any issues we run into should be returned to the LLM for further processing.
		a.toolCalls(ctx, currentRun, opts)

		if currentRun.Done {
			if isChat {
				session.Set(previousExecutionKey, currentRun)
			}

			finalResponse := *currentRun.Response

			if startID != "" && currentRun.PopulatedRequest != nil {
				i := slices.IndexFunc(currentRun.PopulatedRequest.Input, func(msg types.Message) bool {
					return msg.ID == startID
				})
				if i >= 0 {
					finalResponse.InternalMessages = types.ConsolidateTools(currentRun.PopulatedRequest.Input[i:])
				}
			}

			return &finalResponse, nil
		}

		previousRun = currentRun
		currentRun = &types.Execution{
			Request: req.Reset(),
		}
	}
}

func (a *Agents) GetConfigForAgent(ctx context.Context, agentName string) (types.Config, error) {
	config := types.ConfigFromContext(ctx)
	return a.configHook(ctx, config, agentName)
}

func (a *Agents) configHook(ctx context.Context, baseConfig types.Config, agentName string) (types.Config, error) {
	session := mcp.SessionFromContext(ctx).Root()
	var sessionInit types.SessionInitHook
	session.Get(types.SessionInitSessionKey, &sessionInit)

	agent := baseConfig.Agents[agentName]
	if !slices.ContainsFunc(agent.Hooks, func(hook mcp.HookMapping) bool {
		return hook.Name == "config" && slices.Contains(hook.Targets, "nanobot.system/config")
	}) {
		agent.Hooks = append(agent.Hooks, mcp.HookMapping{Name: "config", Targets: []string{"nanobot.system/config"}})
	}
	hookResult, err := mcp.InvokeHooks(ctx, a.registry, agent.Hooks, &types.AgentConfigHook{
		Agent:     &agent.HookAgent,
		Meta:      sessionInit.Meta,
		SessionID: session.ID(),
	}, "config", nil)
	if err != nil {
		return types.Config{}, fmt.Errorf("failed to invoke config hook: %w", err)
	}

	if hookResult.Agent != nil {
		newAgent := types.Agent{
			HookAgent: *hookResult.Agent,
		}
		if baseConfig.Agents == nil {
			baseConfig.Agents = map[string]types.Agent{}
		} else {
			baseConfig.Agents = maps.Clone(baseConfig.Agents)
		}
		if agent.Output != nil {
			newAgent.Output = agent.Output
		}
		baseConfig.Agents[agentName] = newAgent
	}

	if len(hookResult.MCPServers) > 0 {
		if baseConfig.MCPServers == nil {
			baseConfig.MCPServers = map[string]mcp.Server{}
		} else {
			baseConfig.MCPServers = maps.Clone(baseConfig.MCPServers)
		}
		for name, server := range hookResult.MCPServers {
			baseConfig.MCPServers[name] = server.ToMCPServer()
		}
	}

	return baseConfig, nil
}

func (a *Agents) runBefore(ctx context.Context, config types.Config, req types.CompletionRequest) (types.CompletionRequest, *types.CompletionResponse, error) {
	agent := config.Agents[req.GetAgent()]
	resp, err := mcp.InvokeHooks(ctx, a.registry, agent.Hooks, &types.AgentRequestHook{
		Request: &req,
	}, "request", nil)
	if err != nil {
		return req, nil, fmt.Errorf("failed to invoke request hook: %w", err)
	}

	if resp.Request != nil {
		req = *resp.Request
	}

	return req, resp.Response, nil
}

func (a *Agents) runAfter(ctx context.Context, config types.Config, req types.CompletionRequest, resp *types.CompletionResponse) (*types.CompletionResponse, error) {
	agent := config.Agents[req.GetAgent()]
	hookResp, err := mcp.InvokeHooks(ctx, a.registry, agent.Hooks, &types.AgentResponseHook{
		Request:  &req,
		Response: resp,
	}, "response", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to invoke response hook: %w", err)
	}
	if hookResp.Response != nil {
		return hookResp.Response, nil
	}
	return resp, nil
}

func (a *Agents) run(ctx context.Context, config types.Config, run *types.Execution, prev *types.Execution, opts []types.CompletionOptions) error {
	completionRequest, toolMapping, err := a.populateRequest(ctx, config, run, prev, opts)
	if err != nil {
		return err
	}

	// Check if compaction is needed
	agent, agentExists := config.Agents[completionRequest.GetAgent()]
	if agentExists {
		ctxWindowSize := getContextWindowSize(agent.ContextWindow)
		if shouldCompact(completionRequest, ctxWindowSize) {
			var prevCompacted []types.Message
			if prev != nil {
				prevCompacted = prev.CompactedMessages
			}

			result, compactErr := a.compact(ctx, completionRequest, run.Request.Input, prevCompacted)
			if compactErr != nil {
				slog.Error("compaction failed, continuing without", "error", compactErr)
			} else if result != nil {
				completionRequest.Input = result.compactedInput
				run.CompactedMessages = result.archivedMessages
			}
		}
	}
	// Carry forward compacted messages if no compaction this turn
	if run.CompactedMessages == nil && prev != nil {
		run.CompactedMessages = prev.CompactedMessages
	}

	// Don't forget about old tools that might not be in use anymore. If the old name mapped to a
	// different tool we will have a problem but, oh well?
	allToolMappings := types.ToolMappings{}
	if prev != nil {
		maps.Copy(allToolMappings, prev.ToolToMCPServer)
	}
	maps.Copy(allToolMappings, toolMapping)

	run.ToolToMCPServer = allToolMappings

	completionRequest, resp, err := a.runBefore(ctx, config, completionRequest)
	if err != nil {
		return fmt.Errorf("failed to run before agent: %w", err)
	} else if resp != nil {
		run.PopulatedRequest = &completionRequest
		run.Response = resp
		return nil
	}

	run.PopulatedRequest = &completionRequest

	modifiedRequest, resp, err := a.handleUIAction(ctx, config, completionRequest, opts)
	if err != nil {
		return fmt.Errorf("failed to handle UI action: %w", err)
	} else if resp != nil {
		run.Response = resp
		return nil
	}

	resp, err = a.completer.Complete(ctx, modifiedRequest, opts...)
	if err != nil {
		return err
	}

	resp, err = a.runAfter(ctx, config, completionRequest, resp)
	if err != nil {
		return fmt.Errorf("failed to run after agent: %w", err)
	}

	run.Response = resp
	return nil
}
