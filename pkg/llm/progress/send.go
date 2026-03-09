package progress

import (
	"context"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func Send(ctx context.Context, progress *types.CompletionProgress, progressToken any) {
	if progressToken == nil || progressToken == "" {
		return
	}
	session := mcp.SessionFromContext(ctx)
	if session == nil {
		return
	}

	_ = session.SendPayload(ctx, "notifications/progress", mcp.NotificationProgressRequest{
		ProgressToken: progressToken,
		Meta: map[string]any{
			types.CompletionProgressMetaKey: progress,
		},
	})
}
