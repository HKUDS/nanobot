package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

const progressSessionKey = "progress"

type chatCall struct {
	s *Server
}

func (c chatCall) Definition() mcp.Tool {
	return mcp.Tool{
		Name:        types.AgentTool + c.s.agentName,
		Description: types.AgentToolDescription,
		InputSchema: types.ChatInputSchema,
	}
}

func closeProgress(ctx context.Context, session *mcp.Session, err error) {
	var response types.CompletionResponse
	session.Get(progressSessionKey, &response)
	response.HasMore = false
	if err != nil {
		response.Error = err.Error()
	}
	if len(response.InternalMessages) > 0 {
		response.Output = response.InternalMessages[len(response.InternalMessages)-1]
		response.InternalMessages = response.InternalMessages[:len(response.InternalMessages)-1]
		// Sort items to ensure consistent display order: reasoning, content, tools
		sortCompletionItems(&response.Output)
	}
	response.ProgressToken = nil
	session.Set(progressSessionKey, &response)

	_ = session.SendPayload(ctx, "notifications/resources/updated", map[string]any{
		"uri": types.ProgressURI,
	})
}

// sortCompletionItems sorts items by type priority: reasoning first, then content, then tools
func sortCompletionItems(msg *types.Message) {
	if len(msg.Items) <= 1 {
		return
	}

	// Define priority order
	itemPriority := func(item types.CompletionItem) int {
		if item.Reasoning != nil {
			return 0 // Reasoning first
		} else if item.Content != nil {
			return 1 // Content second
		} else if item.ToolCall != nil || item.ToolCallResult != nil {
			return 2 // Tools last
		}
		return 99 // Unknown types at the end
	}

	// Sort using a stable sort to preserve relative order within same priority
	for i := 0; i < len(msg.Items)-1; i++ {
		for j := i + 1; j < len(msg.Items); j++ {
			if itemPriority(msg.Items[i]) > itemPriority(msg.Items[j]) {
				msg.Items[i], msg.Items[j] = msg.Items[j], msg.Items[i]
			}
		}
	}
}

func appendProgress(ctx context.Context, session *mcp.Session, progressMessage *mcp.Message) (*mcp.Message, error) {
	if progressMessage.Method != "notifications/progress" {
		return progressMessage, nil
	}

	var (
		event    progressPayload
		response types.CompletionResponse
	)

	if err := json.Unmarshal(progressMessage.Params, &event); err != nil {
		return progressMessage, nil
	}
	if event.Meta.Progress == nil || event.Meta.Progress.MessageID == "" {
		return progressMessage, nil
	}

	progressItem := event.Meta.Progress.Item
	session.Get(progressSessionKey, &response)
	defer session.Set(progressSessionKey, &response)

	defer func() {
		_ = session.SendPayload(ctx, "notifications/resources/updated", map[string]any{
			"uri": types.ProgressURI,
		})
	}()
	response.HasMore = true

	if progressItem.ToolCallResult != nil {
		for msgIndex, msg := range response.InternalMessages {
			for itemIndex, item := range msg.Items {
				if item.ToolCall != nil {
					if item.ToolCall.CallID == progressItem.ToolCallResult.CallID {
						response.InternalMessages[msgIndex].Items[itemIndex].ToolCallResult = progressItem.ToolCallResult
					}
				}
			}
		}
		return nil, nil
	}

	var (
		currentMessageIndex = -1
		currentItemIndex    = -1
		currentItem         *types.CompletionItem
		now                 = time.Now()
	)

	for msgIndex, msg := range response.InternalMessages {
		if event.Meta.Progress.MessageID == msg.ID {
			currentMessageIndex = msgIndex
			for itemIndex, item := range msg.Items {
				if item.ID == event.Meta.Progress.Item.ID {
					currentItem = &response.InternalMessages[msgIndex].Items[itemIndex]
					currentItemIndex = itemIndex

					if !progressItem.Partial {
						response.InternalMessages[msgIndex].Items[itemIndex] = progressItem
						return nil, nil
					}
				}
			}
		}
	}

	if currentMessageIndex == -1 {
		role := event.Meta.Progress.Role
		if role == "" {
			role = "assistant"
		}
		response.InternalMessages = append(response.InternalMessages, types.Message{
			ID:      event.Meta.Progress.MessageID,
			Created: &now,
			Role:    role,
			HasMore: true,
			Items: []types.CompletionItem{
				progressItem,
			},
		})
		return nil, nil
	}

	if currentItemIndex == -1 {
		response.InternalMessages[currentMessageIndex].Items = append(response.InternalMessages[currentMessageIndex].Items, progressItem)
		// Sort items immediately to maintain correct display order during streaming
		sortCompletionItems(&response.InternalMessages[currentMessageIndex])
		return nil, nil
	}

	if currentItem == nil {
		return nil, nil
	}

	currentItem.HasMore = progressItem.HasMore
	// At this point Partial is always true
	if progressItem.Content != nil {
		currentItem.Content.Text += progressItem.Content.Text
	} else if progressItem.ToolCall != nil && currentItem.ToolCall == nil {
		currentItem.ToolCall = progressItem.ToolCall
	} else if progressItem.ToolCall != nil {
		currentItem.ToolCall.Arguments += progressItem.ToolCall.Arguments
	} else if progressItem.Reasoning != nil && len(progressItem.Reasoning.Summary) > 0 {
		if len(currentItem.Reasoning.Summary) == 0 {
			currentItem.Reasoning.Summary = append(currentItem.Reasoning.Summary, progressItem.Reasoning.Summary[0])
		} else {
			currentItem.Reasoning.Summary[len(currentItem.Reasoning.Summary)-1].Text += progressItem.Reasoning.Summary[0].Text
		}
	}

	return nil, nil
}

func (c chatCall) Invoke(ctx context.Context, msg mcp.Message, payload mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	c.s.describeSession(ctx, payload.Arguments)

	if attachments, _ := payload.Arguments["attachments"].([]any); len(attachments) > 0 {
		var err error
		payload.Arguments["attachments"], err = c.inlineAttachments(ctx, attachments)
		if err != nil {
			return nil, err
		}
	}

	async := msg.Meta()[types.AsyncMetaKey]
	if (async == "true" || async == true) && msg.ProgressToken() != nil {
		nctx := types.NanobotContext(ctx)
		session := mcp.SessionFromContext(ctx)

		ctx := mcp.WithRequestID(session.Context(), mcp.RequestIDFromContext(ctx))
		mcp.SessionFromContext(ctx).Go(types.WithNanobotContext(ctx, nctx), msg, func(ctx context.Context, m mcp.Message) {
			_, _ = c.chatInvoke(ctx, m, payload)
		})
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				{
					Text: fmt.Sprintf("Chat request has been sent to the agent. You can track the progress of the response in the resource %s",
						types.ProgressURI),
				},
				{
					Type:     "resource_link",
					URI:      types.ProgressURI,
					MIMEType: types.ToolResultMimeType,
				},
			},
		}, nil
	}

	return c.chatInvoke(ctx, msg, payload)
}

func (c chatCall) chatInvoke(ctx context.Context, msg mcp.Message, payload mcp.CallToolRequest) (_ *mcp.CallToolResult, retErr error) {
	session := mcp.SessionFromContext(ctx).Parent

	defer func() {
		closeProgress(ctx, session, retErr)
	}()
	defer session.AddFilter(func(ctx context.Context, msg *mcp.Message) (*mcp.Message, error) {
		return appendProgress(ctx, session, msg)
	})()

	session.Set(progressSessionKey, &types.CompletionResponse{
		ProgressToken: msg.ProgressToken(),
	})

	result, err := c.s.runtime.Call(ctx, c.s.agentName, c.s.agentName, payload.Arguments, tools.CallOptions{
		ProgressToken: msg.ProgressToken(),
		LogData: map[string]any{
			"mcpToolName": payload.Name,
		},
	})
	if err != nil {
		return nil, err
	}

	mcpResult := mcp.CallToolResult{
		StructuredContent: result.StructuredContent,
		IsError:           result.IsError,
		Content:           result.Content,
	}

	err = msg.Reply(ctx, mcpResult)
	return &mcpResult, err
}

func GetMessages(ctx context.Context) ([]types.Message, error) {
	var (
		run         types.Execution
		allMessages []types.Message
	)

	session := mcp.SessionFromContext(ctx)
	session.Get(types.PreviousExecutionKey, &run)

	// Prepend archived pre-compaction messages
	if len(run.CompactedMessages) > 0 {
		allMessages = append(allMessages, run.CompactedMessages...)
	}

	// Add current input (includes compaction summary in its natural position)
	if run.PopulatedRequest != nil {
		allMessages = append(allMessages, run.PopulatedRequest.Input...)
	}
	if run.Response != nil {
		allMessages = append(allMessages, run.Response.Output)
	}

	return types.ConsolidateTools(allMessages), nil
}

type progressPayload struct {
	Meta progressPayloadMeta `json:"_meta"`
}

type progressPayloadMeta struct {
	Progress *types.CompletionProgress `json:"ai.nanobot.progress/completion"`
}
