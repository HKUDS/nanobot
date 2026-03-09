package anthropic

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

// NewClient creates a new OpenAI client with the provided API key and base URL.
func NewClient(cfg Config) *Client {
	if cfg.BaseURL == "" {
		cfg.BaseURL = "https://api.anthropic.com/v1"
	}
	if cfg.Headers == nil {
		cfg.Headers = map[string]string{}
	}
	if _, ok := cfg.Headers["x-api-key"]; !ok && cfg.APIKey != "" {
		cfg.Headers["x-api-key"] = cfg.APIKey
	}
	if _, ok := cfg.Headers["anthropic-version"]; !ok {
		cfg.Headers["anthropic-version"] = "2023-06-01"
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
	opt := complete.Complete(opts...)

	req.Stream = true

	data, _ := json.Marshal(req)
	log.Messages(ctx, "anthropic-api", true, data)

	httpReq, err := http.NewRequestWithContext(mcp.UserContext(ctx), http.MethodPost, c.BaseURL+"/messages", bytes.NewBuffer(data))
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
		return nil, fmt.Errorf("failed to get response from Anthropic API: %s %q", httpResp.Status, string(body))
	}

	var (
		lines       = bufio.NewScanner(httpResp.Body)
		resp        Response
		partialJSON = ""
	)

	for lines.Scan() {
		line := lines.Text()

		header, body, ok := strings.Cut(line, ":")
		if !ok || strings.TrimSpace(header) != "data" {
			continue
		}

		var delta DeltaEvent
		body = strings.TrimSpace(body)
		if err := json.Unmarshal([]byte(body), &delta); err != nil {
			slog.Error("failed to decode event", "error", err, "body", body)
			continue
		}
		contentIndex := len(resp.Content) - 1
		switch delta.Type {
		case "message_start":
			resp = delta.Message
		case "content_block_start":
			partialJSON = ""
			resp.Content = append(resp.Content, delta.ContentBlock)
		case "content_block_delta":
			switch delta.Delta.Type {
			case "text_delta":
				if contentIndex >= 0 {
					*resp.Content[contentIndex].Text += delta.Delta.Text
					progress.Send(ctx, &types.CompletionProgress{
						Model:     resp.Model,
						Agent:     agentName,
						MessageID: resp.ID,
						Item: types.CompletionItem{
							ID:      fmt.Sprintf("%s-%d", resp.ID, contentIndex),
							Partial: true,
							HasMore: true,
							Content: &mcp.Content{
								Type: "text",
								Text: delta.Delta.Text,
							},
						},
					}, opt.ProgressToken)
				}
			case "input_json_delta":
				partialJSON += delta.Delta.PartialJSON
				if contentIndex >= 0 {
					progress.Send(ctx, &types.CompletionProgress{
						Model:     resp.Model,
						Agent:     agentName,
						MessageID: resp.ID,
						Item: types.CompletionItem{
							ID:      fmt.Sprintf("%s-%d", resp.ID, contentIndex),
							Partial: true,
							HasMore: true,
							ToolCall: &types.ToolCall{
								CallID:    resp.Content[contentIndex].ID,
								Name:      resp.Content[contentIndex].Name,
								Arguments: delta.Delta.PartialJSON,
							},
						},
					}, opt.ProgressToken)
				}
			}
		case "content_block_stop":
			if contentIndex >= 0 && partialJSON != "" {
				args := map[string]any{}
				if err := json.Unmarshal([]byte(partialJSON), &args); err != nil {
					return nil, fmt.Errorf("failed to unmarshal function call arguments: %w", err)
				}
				resp.Content[contentIndex].Input = args
			}
			if contentIndex >= 0 {
				progress.Send(ctx, &types.CompletionProgress{
					Model:     resp.Model,
					Agent:     agentName,
					MessageID: resp.ID,
					Item: types.CompletionItem{
						Partial: true,
						ID:      fmt.Sprintf("%s-%d", resp.ID, contentIndex),
					},
				}, opt.ProgressToken)
			}
		case "message_delta":
			err := json.Unmarshal([]byte(body), &struct {
				Delta *Response `json:"delta"`
			}{
				Delta: &resp,
			})
			if err != nil {
				return nil, fmt.Errorf("failed to unmarshal message delta: %w", err)
			}
		case "message_stop":
			// nothing to do, but here for completeness
		}
	}

	if err := lines.Err(); err != nil {
		// Check if this was a client-initiated cancellation
		if cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](context.Cause(mcp.UserContext(ctx))); ok && cancelErr != nil {
			// Append the cancellation error as if the assistant sent it
			contentIndex := len(resp.Content) - 1
			if contentIndex < 0 {
				resp.Content = append(resp.Content, Content{
					Type: "text",
					Text: new(string),
				})
				contentIndex = 0
			}

			errorText := "\n\n" + strings.ToUpper(cancelErr.Error())
			if resp.Content[contentIndex].Text != nil {
				*resp.Content[contentIndex].Text += errorText
			} else {
				resp.Content[contentIndex].Text = &errorText
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
			return &resp, nil
		}
	}

	respData, err := json.Marshal(resp)
	if err == nil {
		log.Messages(ctx, "anthropic-api", false, respData)
	}

	return &resp, nil
}
