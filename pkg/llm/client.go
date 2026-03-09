package llm

import (
	"context"
	"encoding/json"
	"errors"
	"maps"
	"strconv"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/llm/anthropic"
	"github.com/nanobot-ai/nanobot/pkg/llm/completions"
	"github.com/nanobot-ai/nanobot/pkg/llm/progress"
	"github.com/nanobot-ai/nanobot/pkg/llm/responses"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

var _ types.Completer = (*Client)(nil)

type Config struct {
	DefaultModel, DefaultMiniModel string
	Responses                      responses.Config
	Anthropic                      anthropic.Config
}

func NewClient(cfg Config) *Client {
	return &Client{
		useCompletions:   cfg.Responses.ChatCompletionAPI,
		defaultModel:     cfg.DefaultModel,
		defaultMiniModel: cfg.DefaultMiniModel,
		cfg:              cfg,
	}
}

type Client struct {
	defaultModel     string
	defaultMiniModel string
	useCompletions   bool
	cfg              Config
}

func (c Client) Complete(ctx context.Context, req types.CompletionRequest, opts ...types.CompletionOptions) (ret *types.CompletionResponse, err error) {
	defer func() {
		if errors.Is(err, context.Canceled) {
			if cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](context.Cause(mcp.UserContext(ctx))); ok && cancelErr != nil {
				err = nil
				ret = &types.CompletionResponse{
					Output: types.Message{
						ID:   uuid.String(),
						Role: "assistant",
						Items: []types.CompletionItem{
							{
								Content: &mcp.Content{
									Type: "text",
									Text: strings.ToUpper(cancelErr.Error()),
								},
							},
						},
					},
				}

				if opt := complete.Complete(opts...); opt.ProgressToken != nil {
					progress.Send(ctx, &types.CompletionProgress{
						MessageID: ret.Output.ID,
						Role:      "assistant",
						Item:      ret.Output.Items[0],
					}, opt.ProgressToken)
				}
			}
		}
		if ret != nil && ret.Agent == "" {
			ret.Agent = req.Agent
		}
	}()

	dynamic := c.dynamicConfig(ctx)

	if req.Model == "default" || req.Model == "" {
		req.Model = dynamic.DefaultModel
	}
	if req.Model == "mini" {
		req.Model = dynamic.DefaultMiniModel
	}

	opt := complete.Complete(opts...)
	if opt.ProgressToken != nil && len(req.Input) > 0 {
		lastMsg := req.Input[len(req.Input)-1]
		if lastMsg.ID != "" && lastMsg.Role == "user" {
			for _, item := range lastMsg.Items {
				progress.Send(ctx, &types.CompletionProgress{
					Model:     req.Model,
					MessageID: lastMsg.ID,
					Role:      lastMsg.Role,
					Item:      item,
				}, opt.ProgressToken)
			}
		}
	}

	if strings.HasPrefix(req.Model, "claude") {
		return anthropic.NewClient(dynamic.Anthropic).Complete(ctx, req, opts...)
	}
	if dynamic.Responses.ChatCompletionAPI {
		return completions.NewClient(completions.Config{
			APIKey:  dynamic.Responses.APIKey,
			BaseURL: dynamic.Responses.BaseURL,
			Headers: maps.Clone(dynamic.Responses.Headers),
		}).Complete(ctx, req, opts...)
	}
	return responses.NewClient(dynamic.Responses).Complete(ctx, req, opts...)
}

func (c Client) dynamicConfig(ctx context.Context) Config {
	cfg := Config{
		DefaultModel:     c.defaultModel,
		DefaultMiniModel: c.defaultMiniModel,
		Responses: responses.Config{
			ChatCompletionAPI: c.useCompletions,
			APIKey:            c.cfg.Responses.APIKey,
			BaseURL:           c.cfg.Responses.BaseURL,
			Headers:           maps.Clone(c.cfg.Responses.Headers),
		},
		Anthropic: anthropic.Config{
			APIKey:  c.cfg.Anthropic.APIKey,
			BaseURL: c.cfg.Anthropic.BaseURL,
			Headers: maps.Clone(c.cfg.Anthropic.Headers),
		},
	}

	session := mcp.SessionFromContext(ctx)
	if session == nil {
		return cfg
	}

	env := session.GetEnvMap()
	if v := strings.TrimSpace(env["NANOBOT_DEFAULT_MODEL"]); v != "" {
		cfg.DefaultModel = v
	}
	if v := strings.TrimSpace(env["NANOBOT_DEFAULT_MINI_MODEL"]); v != "" {
		cfg.DefaultMiniModel = v
	}
	if v := strings.TrimSpace(env["OPENAI_API_KEY"]); v != "" {
		cfg.Responses.APIKey = v
	}
	if v := strings.TrimSpace(env["OPENAI_BASE_URL"]); v != "" {
		cfg.Responses.BaseURL = v
	}
	if v := strings.TrimSpace(env["OPENAI_CHAT_COMPLETION_API"]); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			cfg.Responses.ChatCompletionAPI = b
		}
	}
	if hdrs := parseHeaderEnv(env["OPENAI_HEADERS"]); len(hdrs) > 0 {
		cfg.Responses.Headers = hdrs
	}

	if v := strings.TrimSpace(env["ANTHROPIC_API_KEY"]); v != "" {
		cfg.Anthropic.APIKey = v
	}
	if v := strings.TrimSpace(env["ANTHROPIC_BASE_URL"]); v != "" {
		cfg.Anthropic.BaseURL = v
	}
	if hdrs := parseHeaderEnv(env["ANTHROPIC_HEADERS"]); len(hdrs) > 0 {
		cfg.Anthropic.Headers = hdrs
	}

	return cfg
}

func parseHeaderEnv(raw string) map[string]string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}

	result := map[string]string{}
	if err := json.Unmarshal([]byte(raw), &result); err == nil {
		return result
	}

	for part := range strings.SplitSeq(raw, ",") {
		k, v, ok := strings.Cut(part, "=")
		if !ok {
			continue
		}
		k = strings.TrimSpace(k)
		v = strings.TrimSpace(v)
		if k != "" {
			result[k] = v
		}
	}
	if len(result) == 0 {
		return nil
	}
	return result
}
