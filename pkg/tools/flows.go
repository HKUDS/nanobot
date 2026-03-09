package tools

import (
	"context"
	"fmt"
	"maps"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func (s *Service) getPrompt(ctx context.Context, prompt string, args map[string]string) (string, error) {
	server, prompt, ok := strings.Cut(prompt, "/")
	if !ok {
		prompt = server
	}

	promptResult, err := s.GetPrompt(ctx, server, prompt, args)
	if err != nil {
		return "", fmt.Errorf("failed to get prompt %s from server %s: %w", prompt, server, err)
	}

	for _, msg := range promptResult.Messages {
		if msg.Content.Text != "" {
			return msg.Content.Text, nil
		}
	}
	return "", nil
}

func (s *Service) newGlobals(ctx context.Context, vars map[string]any, opt ...CallOptions) map[string]any {
	session := mcp.SessionFromContext(ctx)
	attr := session.Attributes()
	data := map[string]any{}
	data["prompt"] = func(target string, args map[string]string) (string, error) {
		return s.getPrompt(ctx, target, args)
	}
	data["nanobot"] = attr
	data["call"] = func(target string, args map[string]any) (map[string]any, error) {
		return s.callFromScript(ctx, target, args, CallOptions{
			ProgressToken: complete.Complete(opt...).ProgressToken,
		})
	}
	servers := map[string]any{}
	data["servers"] = servers

	for k, v := range attr {
		cf, ok := v.(*clientFactory)
		if !ok {
			continue
		}
		serverName, ok := strings.CutPrefix(k, "clients/")
		if !ok {
			continue
		}
		var instructions string
		if cf.client != nil && cf.client.Session != nil {
			instructions = cf.client.Session.InitializeResult.Instructions
		}
		servers[serverName] = map[string]any{
			"instructions": instructions,
		}
	}

	c := types.ConfigFromContext(ctx)
	for serverName := range c.MCPServers {
		if _, ok := servers[serverName]; !ok {
			servers[serverName] = map[string]any{
				"instructions": "",
			}
		}
	}

	maps.Copy(data, vars)
	return data
}

func (s *Service) callFromScript(ctx context.Context, target string, args any, opt CallOptions) (map[string]any, error) {
	server, tool, _ := strings.Cut(target, "/")
	ret, err := s.Call(ctx, server, tool, args, opt)
	if err != nil {
		return nil, err
	}
	return toOutput(ret), nil
}

func toOutput(ret *types.CallResult) map[string]any {
	if ret == nil {
		return nil
	}

	output := map[string]any{
		"content":           ret.Content,
		"isError":           ret.IsError,
		"structuredContent": ret.StructuredContent,
	}
	if ret.Content == nil {
		output["content"] = make([]mcp.Content, 0)
	}
	for i := len(ret.Content) - 1; i >= 0; i-- {
		if ret.Content[i].Text != "" {
			output["output"] = ret.Content[i].Text
		}
		if ret.StructuredContent != nil {
			output["output"] = ret.StructuredContent
		}
	}
	return output
}
