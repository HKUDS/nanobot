package types

import (
	"context"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

type Context struct {
	User    mcp.User
	Config  ConfigFactory
	Profile []string
}

type contextKey struct{}

func WithNanobotContext(ctx context.Context, nc Context) context.Context {
	return context.WithValue(ctx, contextKey{}, nc)
}

func NanobotContext(ctx context.Context) Context {
	c, _ := ctx.Value(contextKey{}).(Context)
	return c
}
