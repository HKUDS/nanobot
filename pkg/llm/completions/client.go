package completions

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/llm/progress"
	"github.com/nanobot-ai/nanobot/pkg/log"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type Client struct {
	Config
}

type Config struct {
	APIKey  string
	BaseURL string
	Headers map[string]string
}

// NewClient creates a new OpenAI Chat Completions client with the provided API key and base URL.
func NewClient(cfg Config) *Client {
	if cfg.BaseURL == "" {
		cfg.BaseURL = "https://api.openai.com/v1"
	}
	// Remove trailing slash from BaseURL to avoid double slashes in URL construction
	cfg.BaseURL = strings.TrimSuffix(cfg.BaseURL, "/")
	if cfg.Headers == nil {
		cfg.Headers = map[string]string{}
	}
	if _, ok := cfg.Headers["Authorization"]; !ok && cfg.APIKey != "" {
		cfg.Headers["Authorization"] = "Bearer " + cfg.APIKey
	}
	if _, ok := cfg.Headers["Content-Type"]; !ok {
		cfg.Headers["Content-Type"] = "application/json"
	}

	return &Client{
		Config: cfg,
	}
}

func (c *Client) Complete(ctx context.Context, completionRequest types.CompletionRequest, opts ...types.CompletionOptions) (*types.CompletionResponse, error) {
	req, err := toRequest(&completionRequest)
	if err != nil {
		return nil, err
	}

	ts := time.Now()
	resp, err := c.complete(ctx, completionRequest.Agent, req, opts...)
	if err != nil {
		return nil, err
	}

	return toResponse(resp, ts)
}

func (c *Client) complete(ctx context.Context, agentName string, req Request, opts ...types.CompletionOptions) (*Response, error) {
	var (
		opt = complete.Complete(opts...)
	)

	req.Stream = true
	req.StreamOptions = &StreamOptions{IncludeUsage: true}

	data, _ := json.Marshal(req)
	log.Messages(ctx, "completions-api", true, data)
	httpReq, err := http.NewRequestWithContext(mcp.UserContext(ctx), http.MethodPost, c.BaseURL+"/chat/completions", bytes.NewBuffer(data))
	if err != nil {
		return nil, err
	}
	for key, value := range c.Headers {
		httpReq.Header.Set(key, value)
	}

	httpResp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("failed to get response from OpenAI Chat Completions API: %s %q", httpResp.Status, string(body))
	}

	var (
		lines       = bufio.NewScanner(httpResp.Body)
		resp        Response
		initialized = false
		toolCalls   = make(map[int]*ToolCall)
	)

	for lines.Scan() {
		line := lines.Text()

		// Handle SSE format
		if !strings.HasPrefix(line, "data: ") {
			continue
		}

		data := strings.TrimPrefix(line, "data: ")
		data = strings.TrimSpace(data)

		if data == "[DONE]" {
			break
		}

		var chunk StreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			slog.Error("failed to decode streaming chunk", "error", err, "data", data)
			continue
		}

		// Initialize response from first chunk
		if !initialized {
			resp = Response{
				ID:                chunk.ID,
				Object:            "chat.completion",
				Created:           chunk.Created,
				Model:             chunk.Model,
				SystemFingerprint: chunk.SystemFingerprint,
				Choices:           []Choice{{Index: 0, Message: &Message{Role: "assistant"}}},
			}
			initialized = true
		}

		// Handle usage information
		if chunk.Usage != nil {
			resp.Usage = chunk.Usage
		}

		// Process choice deltas
		for _, choice := range chunk.Choices {
			if choice.Index >= len(resp.Choices) {
				continue
			}

			delta := choice.Delta
			if delta == nil {
				continue
			}

			// Determine if this is the final chunk for this choice
			isFinished := choice.FinishReason != nil

			// Handle role
			if delta.Role != "" && resp.Choices[choice.Index].Message != nil {
				resp.Choices[choice.Index].Message.Role = delta.Role
			}

			// Handle content
			if delta.Content != nil && *delta.Content != "" {
				if resp.Choices[choice.Index].Message.Content.Text == nil {
					resp.Choices[choice.Index].Message.Content.Text = new(string)
				}
				*resp.Choices[choice.Index].Message.Content.Text += *delta.Content

				progress.Send(ctx, &types.CompletionProgress{
					Model:     resp.Model,
					Agent:     agentName,
					MessageID: resp.ID,
					Item: types.CompletionItem{
						ID:      fmt.Sprintf("%s-%d", resp.ID, choice.Index),
						Partial: true,
						HasMore: !isFinished,
						Content: &mcp.Content{
							Type: "text",
							Text: *delta.Content,
						},
					},
				}, opt.ProgressToken)
			}

			// Handle reasoning (for reasoning models like DeepSeek-R1, QwQ, etc.)
			if delta.Reasoning != nil && *delta.Reasoning != "" {
				if resp.Choices[choice.Index].Message.Reasoning == nil {
					resp.Choices[choice.Index].Message.Reasoning = new(string)
				}
				*resp.Choices[choice.Index].Message.Reasoning += *delta.Reasoning

				progress.Send(ctx, &types.CompletionProgress{
					Model:     resp.Model,
					Agent:     agentName,
					MessageID: resp.ID,
					Item: types.CompletionItem{
						ID:      fmt.Sprintf("%s-reasoning-%d", resp.ID, choice.Index),
						Partial: true,
						HasMore: !isFinished,
						Reasoning: &types.Reasoning{
							Summary: []types.SummaryText{
								{
									Text: *delta.Reasoning,
								},
							},
						},
					},
				}, opt.ProgressToken)
			}

			// Handle tool calls
			if delta.ToolCalls != nil {
				for i, toolCall := range delta.ToolCalls {
					index := i
					if toolCall.Index != nil {
						index = *toolCall.Index
					}
					if _, exists := toolCalls[index]; !exists {
						toolCalls[index] = &ToolCall{
							ID:   toolCall.ID,
							Type: toolCall.Type,
							Function: FunctionCall{
								Name:      toolCall.Function.Name,
								Arguments: toolCall.Function.Arguments,
							},
						}
					} else {
						// Append to existing tool call arguments
						toolCalls[index].Function.Arguments += toolCall.Function.Arguments
					}

					progress.Send(ctx, &types.CompletionProgress{
						Model:     resp.Model,
						Agent:     agentName,
						MessageID: resp.ID,
						Item: types.CompletionItem{
							ID:      fmt.Sprintf("%s-t-%d", resp.ID, index),
							Partial: true,
							HasMore: !isFinished,
							ToolCall: &types.ToolCall{
								CallID:    toolCalls[index].ID,
								Name:      toolCalls[index].Function.Name,
								Arguments: toolCall.Function.Arguments,
							},
						},
					}, opt.ProgressToken)
				}
			}

			// Handle finish reason
			if choice.FinishReason != nil {
				resp.Choices[choice.Index].FinishReason = choice.FinishReason
			}

			// Handle refusal
			if delta.Refusal != nil {
				resp.Choices[choice.Index].Message.Refusal = delta.Refusal
			}
		}
	}

	if err := lines.Err(); err != nil {
		// Check if this was a client-initiated cancellation
		if cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](context.Cause(mcp.UserContext(ctx))); ok && cancelErr != nil {
			// Ensure response is initialized
			if !initialized {
				resp = Response{
					Object:  "chat.completion",
					Choices: []Choice{{Index: 0, Message: &Message{Role: "assistant"}}},
				}
			}

			contentIndex := 0
			errorText := "\n\n" + strings.ToUpper(cancelErr.Error())
			if resp.Choices[contentIndex].Message.Content.Text != nil {
				*resp.Choices[contentIndex].Message.Content.Text += errorText
			} else {
				resp.Choices[contentIndex].Message.Content.Text = &errorText
			}

			// Send progress notification with the error text
			progress.Send(ctx, &types.CompletionProgress{
				Model:     resp.Model,
				Agent:     agentName,
				MessageID: resp.ID,
				Item: types.CompletionItem{
					ID:      fmt.Sprintf("%s-%d", resp.ID, contentIndex),
					Partial: true,
					Content: &mcp.Content{
						Type: "text",
						Text: errorText,
					},
				},
			}, opt.ProgressToken)

			// Convert tool calls map to slice before returning
			if len(toolCalls) > 0 {
				resp.Choices[0].Message.ToolCalls = make([]ToolCall, len(toolCalls))
				for i, toolCall := range toolCalls {
					resp.Choices[0].Message.ToolCalls[i] = *toolCall
				}
			}

			respData, err := json.Marshal(resp)
			if err == nil {
				log.Messages(ctx, "completions-api", false, respData)
			}

			return &resp, nil
		}

		return nil, fmt.Errorf("failed to read streaming response: %w", err)
	}

	// Convert tool calls map to slice
	if len(toolCalls) > 0 {
		resp.Choices[0].Message.ToolCalls = make([]ToolCall, len(toolCalls))
		for i, toolCall := range toolCalls {
			resp.Choices[0].Message.ToolCalls[i] = *toolCall
		}
	}

	respData, err := json.Marshal(resp)
	if err == nil {
		log.Messages(ctx, "completions-api", false, respData)
	}

	return &resp, nil
}
