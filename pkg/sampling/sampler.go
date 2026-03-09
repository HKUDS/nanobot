package sampling

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

var ErrNoMatchingModel = fmt.Errorf("no matching model found")

type Sampler struct {
	completer types.Completer
}

func NewSampler(completer types.Completer) *Sampler {
	return &Sampler{
		completer: completer,
	}
}

type scored struct {
	score float64
	model string
}

func (s *Sampler) sortModels(config types.Config, preferences mcp.ModelPreferences) []string {
	var scoredModels []scored

	for _, modelKey := range slices.Sorted(maps.Keys(config.Agents)) {
		model := config.Agents[modelKey]
		cost := model.Cost
		if preferences.CostPriority != nil {
			cost *= *preferences.CostPriority
		}
		speed := model.Speed
		if preferences.SpeedPriority != nil {
			speed *= *preferences.SpeedPriority
		}
		intelligence := model.Intelligence
		if preferences.IntelligencePriority != nil {
			intelligence *= *preferences.IntelligencePriority
		}
		scoredModels = append(scoredModels, scored{
			score: cost + speed + intelligence,
			model: modelKey,
		})
	}

	sort.Slice(scoredModels, func(i, j int) bool {
		return scoredModels[i].score > scoredModels[j].score
	})

	models := make([]string, len(scoredModels))
	for i, scoredModel := range scoredModels {
		models[i] = scoredModel.model
	}
	return models
}

func (s *Sampler) getMatchingModel(config types.Config, req *mcp.CreateMessageRequest) (string, bool) {
	// Agent by name
	for _, model := range req.ModelPreferences.Hints {
		if _, ok := config.Agents[model.Name]; ok {
			return model.Name, true
		}
	}

	// Model by alias
	for _, model := range req.ModelPreferences.Hints {
		for _, modelKey := range slices.Sorted(maps.Keys(config.Agents)) {
			if slices.Contains(config.Agents[modelKey].Aliases, model.Name) {
				return modelKey, true
			}
		}
	}

	models := s.sortModels(config, req.ModelPreferences)
	if len(models) == 0 {
		return "", false
	}

	return models[0], true
}

type SamplerOptions struct {
	ProgressToken      any
	Continue           bool
	Chat               *bool
	NewThread          *bool
	ToolChoice         *mcp.ToolChoice
	Tools              []mcp.Tool
	ToolIncludeContext string
	ToolSource         string
}

func (s SamplerOptions) Merge(other SamplerOptions) (result SamplerOptions) {
	result.ProgressToken = complete.Last(s.ProgressToken, other.ProgressToken)
	result.Continue = complete.Last(s.Continue, other.Continue)
	result.Chat = complete.Last(s.Chat, other.Chat)
	result.ToolChoice = complete.Last(s.ToolChoice, other.ToolChoice)
	result.Tools = append(s.Tools, other.Tools...)
	result.ToolIncludeContext = complete.Last(s.ToolIncludeContext, other.ToolIncludeContext)
	result.ToolSource = complete.Last(s.ToolSource, other.ToolSource)
	return
}

func (s *Sampler) Sample(ctx context.Context, req mcp.CreateMessageRequest, opts ...SamplerOptions) (*types.CallResult, error) {
	opt := complete.Complete(opts...)
	config := types.ConfigFromContext(ctx)

	model, ok := s.getMatchingModel(config, &req)
	if !ok {
		return nil, ErrNoMatchingModel
	}

	request := types.CompletionRequest{
		Model: model,
	}

	if req.MaxTokens != 0 {
		request.MaxTokens = req.MaxTokens
	}
	if req.SystemPrompt != "" {
		request.SystemPrompt = req.SystemPrompt
	}
	if req.Temperature != nil {
		request.Temperature = req.Temperature
	}

	var currentRole string
	for _, msg := range req.Messages {
		role := msg.Role
		if role == "" {
			role = "user"
		}

		var id string
		if opt.ProgressToken != nil {
			id = fmt.Sprint(opt.ProgressToken)
		}
		if id != "" && len(request.Input) > 0 {
			id = fmt.Sprintf("%s-%d", id, len(request.Input))
		}
		if id == "" {
			id = uuid.String()
		}

		forceNewMessage := role != currentRole
		if !forceNewMessage && len(msg.Content) > 0 && msg.Content[0].Meta != nil {
			if hidden, ok := msg.Content[0].Meta[types.AttachmentMetaKey].(bool); ok && hidden {
				forceNewMessage = true
			}
		}

		if forceNewMessage {
			now := time.Now()
			request.Input = append(request.Input, types.Message{
				ID:      id,
				Created: &now,
				Role:    role,
			})
			currentRole = role
		}

		inputIndex := len(request.Input) - 1
		for _, currentContent := range msg.Content {
			var (
				content        *mcp.Content
				toolCall       *types.ToolCall
				toolCallResult *types.ToolCallResult
			)

			switch currentContent.Type {
			case "tool_use":
				input, err := json.Marshal(currentContent.Input)
				if err != nil {
					return nil, fmt.Errorf("failed to marshal tool input for %s: %w", currentContent.Name, err)
				}
				toolCall = &types.ToolCall{
					Name:      currentContent.Name,
					Arguments: string(input),
					CallID:    currentContent.ID,
				}
			case "tool_result":
				toolCallResult = &types.ToolCallResult{
					CallID: currentContent.ToolUseID,
					Output: types.CallResult{
						Content:           currentContent.Content,
						IsError:           currentContent.IsError,
						StructuredContent: currentContent.StructuredContent,
					},
				}
			default:
				content = &currentContent
			}

			itemsLength := len(request.Input[inputIndex].Items)
			request.Input[inputIndex].Items = append(request.Input[inputIndex].Items, types.CompletionItem{
				ID:             fmt.Sprintf("%s_%d", id, itemsLength),
				Content:        content,
				ToolCall:       toolCall,
				ToolCallResult: toolCallResult,
			})
		}
	}

	completeOptions := types.CompletionOptions{
		ProgressToken:      opt.ProgressToken,
		Chat:               opt.Chat,
		ToolChoice:         opt.ToolChoice,
		Tools:              opt.Tools,
		ToolIncludeContext: opt.ToolIncludeContext,
		ToolSource:         opt.ToolSource,
	}

	resp, err := s.completer.Complete(ctx, request, completeOptions)
	if err != nil {
		return nil, err
	}

	if _, ok := config.Agents[request.Model]; ok {
		resp.Agent = request.Model
	}

	return CompletionResponseToCallResult(resp, false, opt.Tools)
}

func CompletionResponseToCallResult(resp *types.CompletionResponse, includeMessages bool, externalTools []mcp.Tool) (*types.CallResult, error) {
	result := &types.CallResult{
		Model:   resp.Model,
		IsError: resp.Error != "",
	}

	for _, output := range resp.Output.Items {
		if output.ToolCallResult != nil {
			cp := output.ToolCallResult.Output
			result = &cp
			break
		}
		if output.ToolCall != nil {
			for _, tool := range externalTools {
				if tool.Name == output.ToolCall.Name {
					input := map[string]any{}
					if output.ToolCall.Arguments != "" {
						if err := json.Unmarshal([]byte(output.ToolCall.Arguments), &input); err != nil {
							return nil, fmt.Errorf("failed to unmarshal tool arguments for %s: %w", tool.Name, err)
						}
					}
					result.Content = append(result.Content, mcp.Content{
						Type:  "tool_use",
						ID:    output.ToolCall.CallID,
						Name:  tool.Name,
						Input: input,
					})
				}
			}
		}
		if output.Content == nil || (output.Content.Type == "text" && output.Content.Text == "") {
			// ignore empty string content
			continue
		}
		result.Content = append(result.Content, *output.Content)
	}

	if resp.Error != "" {
		result.IsError = true
		result.Content = append(result.Content, mcp.Content{
			Type: "text",
			Text: resp.Error,
		})
	}

	if len(result.Content) == 0 {
		result.Content = append(result.Content, mcp.Content{
			Type: "text",
			Text: "[NO CONTENT]",
		})
	}

	if includeMessages {
		outputMessages := append(resp.InternalMessages, resp.Output)
		if resp.Error != "" {
			outputMessages = append(outputMessages, types.Message{
				ID:   fmt.Sprintf("%x", sha256.Sum256([]byte(resp.Error)))[:12],
				Role: "assistant",
				Items: []types.CompletionItem{
					{
						Content: &mcp.Content{
							Type: "resource",
							Resource: &mcp.EmbeddedResource{
								MIMEType: types.ErrorMimeType,
								Text:     resp.Error,
							},
						},
					},
				},
			})
		}

		for _, msg := range outputMessages {
			if len(msg.Items) == 0 {
				// Empty message, typically happens in there is an error
				continue
			}
			textData, err := json.Marshal(msg)
			if err != nil {
				return nil, fmt.Errorf("failed to marshal message: %w", err)
			}

			result.Content = append(result.Content, mcp.Content{
				Type: "resource",
				Resource: &mcp.EmbeddedResource{
					URI:      fmt.Sprintf(types.MessageURI, msg.ID),
					MIMEType: types.MessageMimeType,
					Text:     string(textData),
				},
			})
		}
	} else {
		for _, msg := range append(resp.InternalMessages, resp.Output) {
			for _, item := range msg.Items {
				if item.ToolCallResult != nil {
					for _, content := range item.ToolCallResult.Output.Content {
						if strings.HasPrefix(content.URI, "ui://") ||
							(content.Resource != nil && strings.HasPrefix(content.Resource.URI, "ui://")) {
							result.Content = append(result.Content, content)
						}
					}
				}
			}
		}
	}

	return result, nil
}
