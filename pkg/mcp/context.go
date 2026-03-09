package mcp

import (
	"context"

	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
)

var sessionKey = struct{}{}

func SessionFromContext(ctx context.Context) *Session {
	if ctx == nil {
		return nil
	}
	s, ok := ctx.Value(sessionKey).(*Session)
	if !ok {
		return nil
	}
	return s
}

func WithSession(ctx context.Context, s *Session) context.Context {
	if s == nil {
		return ctx
	}
	return context.WithValue(ctx, sessionKey, s)
}

type tokenKey struct{}

func WithToken(ctx context.Context, token string) context.Context {
	return context.WithValue(ctx, tokenKey{}, token)
}

func TokenFromContext(ctx context.Context) string {
	token, _ := ctx.Value(tokenKey{}).(string)
	return token
}

type userKey struct{}

func WithUser(ctx context.Context, user User) context.Context {
	return context.WithValue(ctx, userKey{}, user)
}

func UserFromContext(ctx context.Context) User {
	user, _ := ctx.Value(userKey{}).(User)
	return user
}

type auditLogKey struct{}

func WithAuditLog(ctx context.Context, auditLog *auditlogs.MCPAuditLog) context.Context {
	if auditLog == nil {
		return ctx
	}
	return context.WithValue(ctx, auditLogKey{}, auditLog)
}

func AuditLogFromContext(ctx context.Context) *auditlogs.MCPAuditLog {
	auditLog, _ := ctx.Value(auditLogKey{}).(*auditlogs.MCPAuditLog)
	return auditLog
}

type mcpServerConfigKey struct{}

func WithMCPServerConfig(ctx context.Context, config Server) context.Context {
	return context.WithValue(ctx, mcpServerConfigKey{}, config)
}

func MCPServerConfigFromContext(ctx context.Context) Server {
	config, _ := ctx.Value(mcpServerConfigKey{}).(Server)
	return config
}

type requestIDKey struct{}

func WithRequestID(ctx context.Context, requestID any) context.Context {
	return context.WithValue(ctx, requestIDKey{}, requestID)
}

func RequestIDFromContext(ctx context.Context) any {
	return ctx.Value(requestIDKey{})
}

type userCtxKey struct{}

func withUserCtx(ctx, userCtx context.Context) context.Context {
	return context.WithValue(ctx, userCtxKey{}, userCtx)
}

func UserContext(ctx context.Context) context.Context {
	userCtx, _ := ctx.Value(userCtxKey{}).(context.Context)
	if userCtx == nil {
		return ctx
	}
	return userCtx
}
