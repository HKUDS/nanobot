package responses

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"log/slog"

	llmProgress "github.com/nanobot-ai/nanobot/pkg/llm/progress"
	"github.com/nanobot-ai/nanobot/pkg/log"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func progressResponse(ctx context.Context, agentName, modelName string, resp *http.Response, progressToken any) (response Response, seen bool, err error) {
	lines := bufio.NewScanner(resp.Body)
	defer resp.Body.Close()

	progress := types.CompletionProgress{
		Agent: agentName,
		Model: modelName,
	}

	var (
		accumulatedText string
		accumulatedArgs string
		outputs         []ResponseOutput
	)
	for lines.Scan() {
		line := lines.Text()

		header, body, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		switch strings.TrimSpace(header) {
		case "data":
			var event Progress
			body = strings.TrimSpace(body)
			data := []byte(body)
			if err := json.Unmarshal(data, &event); err != nil {
				slog.Error("failed to decode event", "error", err, "body", body)
				continue
			}

			switch event.Type {
			case "response.created":
				progress.Model = event.Response.Model
				progress.MessageID = event.Response.ID
			case "response.output_item.added":
				switch event.Item.Type {
				case "function_call":
					progress.Item = types.CompletionItem{
						Partial: true,
						HasMore: true,
						ID:      event.Item.ID,
						ToolCall: &types.ToolCall{
							CallID: event.Item.CallID,
							Name:   event.Item.Name,
						},
					}
				case "message":
					progress.Item = types.CompletionItem{
						Partial: true,
						HasMore: true,
						ID:      event.Item.ID,
						Content: &mcp.Content{
							Type: "text",
						},
					}
				}
			case "response.function_call_arguments.delta":
				accumulatedArgs += event.Delta
				progress.Item.ToolCall.Arguments = event.Delta
				llmProgress.Send(ctx, &progress, progressToken)
			case "response.output_item.done":
				// Save completed output item
				switch event.Item.Type {
				case "function_call":
					outputs = append(outputs, ResponseOutput{
						FunctionCall: &FunctionCall{
							ID:        event.Item.ID,
							CallID:    event.Item.CallID,
							Name:      event.Item.Name,
							Arguments: accumulatedArgs,
						},
					})
				case "message":
					outputs = append(outputs, ResponseOutput{
						Message: &Message{
							ID:   event.Item.ID,
							Role: event.Item.Role,
							Content: []MessageContent{
								{OutputText: &OutputText{Text: accumulatedText}},
							},
						},
					})
				}
				accumulatedText = ""
				accumulatedArgs = ""

				// Send progress notification
				if progress.Item.ID != "" {
					progress.Item = types.CompletionItem{
						Partial: true,
						ID:      progress.Item.ID,
					}
					llmProgress.Send(ctx, &progress, progressToken)
				}
				progress.Item = types.CompletionItem{}
			case "response.output_text.delta":
				accumulatedText += event.Delta
				if progress.Item.Content != nil {
					progress.Item.Content.Text = event.Delta
					llmProgress.Send(ctx, &progress, progressToken)
				}
			}

			if event.Type == "response.completed" || event.Type == "response.failed" || event.Type == "response.incomplete" {
				log.Messages(ctx, "responses-api", false, data)
				response = event.Response
				seen = true
			}
		}
	}

	err = lines.Err()
	if err != nil {
		// Check if this was a client-initiated cancellation
		if cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](context.Cause(mcp.UserContext(ctx))); ok {
			// Append the cancellation error as if the assistant sent it
			errorText := "\n\n" + strings.ToUpper(cancelErr.Error())
			if progress.Item.Content == nil {
				progress.Item.Content = &mcp.Content{
					Type: "text",
				}
			}
			progress.Item.Content.Text = errorText
			progress.Item.HasMore = false

			// Send progress notification with the error text
			llmProgress.Send(ctx, &progress, progressToken)

			// Construct Response from accumulated streaming data
			response = Response{
				Model:  progress.Model,
				ID:     progress.MessageID,
				Output: outputs,
			}

			// Append the error text as a message output (mirroring client.go cancellation handling)
			outputIndex := len(response.Output) - 1
			if outputIndex < 0 || response.Output[outputIndex].Message == nil {
				response.Output = append(response.Output, ResponseOutput{
					Message: &Message{
						Role:    "assistant",
						Content: []MessageContent{},
					},
				})
				outputIndex = len(response.Output) - 1
			}

			contentIndex := len(response.Output[outputIndex].Message.Content) - 1
			if contentIndex < 0 {
				response.Output[outputIndex].Message.Content = append(response.Output[outputIndex].Message.Content, MessageContent{
					OutputText: &OutputText{},
				})
				contentIndex = 0
			}

			if response.Output[outputIndex].Message.Content[contentIndex].OutputText != nil {
				if response.Output[outputIndex].Message.Content[contentIndex].OutputText.Text != "" {
					accumulatedText = response.Output[outputIndex].Message.Content[contentIndex].OutputText.Text
				}
				response.Output[outputIndex].Message.Content[contentIndex].OutputText.Text = accumulatedText + errorText
			} else {
				response.Output[outputIndex].Message.Content[contentIndex].OutputText = &OutputText{
					Text: accumulatedText + errorText,
				}
			}

			err = nil
			seen = true
		}
	}
	return
}
