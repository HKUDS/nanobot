package confirm

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

const Timeout = 15 * time.Minute

type Service struct {
}

func New() *Service {
	return &Service{}
}

func (*Service) HandleAuthURL(ctx context.Context, mcpServerName, url string) (bool, error) {
	session := mcp.SessionFromContext(ctx)
	if session == nil {
		return false, fmt.Errorf("no session found in context")
	}

	for session.Parent != nil {
		session = session.Parent
	}

	meta := map[string]any{
		types.MetaPrefix + "oauth-url":   url,
		types.MetaPrefix + "server-name": mcpServerName,
	}
	metaStr, _ := json.Marshal(meta)

	elicit := mcp.ElicitRequest{
		Message: fmt.Sprintf("MCP server %s requires authorization, please visit the following URL to continue: %s", mcpServerName, url),
		RequestedSchema: mcp.PrimitiveSchema{
			Type:       "object",
			Properties: map[string]mcp.PrimitiveProperty{},
		},
		Meta: metaStr,
	}

	var elicitResponse mcp.ElicitResult

	if err := session.Exchange(ctx, "elicitation/create", elicit, &elicitResponse); err != nil {
		return false, fmt.Errorf("failed to elicit confirmation: %w", err)
	}

	switch elicitResponse.Action {
	case "accept":
		return true, nil
	case "reject":
		return false, fmt.Errorf("user has rejected authorization for server %s", mcpServerName)
	default:
		return false, fmt.Errorf("user has canceled authorization for server %s", mcpServerName)
	}
}
