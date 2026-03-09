package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

type PendingElicitation struct {
	ID     any             `json:"id"`
	Params json.RawMessage `json:"params"`
}

func (p PendingElicitation) Serialize() (any, error) {
	data, err := json.Marshal(p)
	if err != nil {
		return nil, err
	}
	var m any
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return m, nil
}

func (p PendingElicitation) Deserialize(v any) (any, error) {
	data, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var result PendingElicitation
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, err
	}
	return result, nil
}

const pendingElicitationKey = "pending-elicitation"

func ExchangeElicitation(ctx context.Context, session *mcp.Session, elicit any, result any) error {
	root := session.Root()
	if root == nil {
		return fmt.Errorf("no root session found")
	}

	msg, err := mcp.NewMessageWithID("elicitation/create", elicit)
	if err != nil {
		return fmt.Errorf("failed to create elicitation message: %w", err)
	}

	root.Set(pendingElicitationKey, PendingElicitation{
		ID:     msg.ID,
		Params: msg.Params,
	})

	err = root.Exchange(ctx, "elicitation/create", msg, result)
	if err == nil || errors.Is(err, mcp.ErrNoReader) {
		root.Delete(pendingElicitationKey)
	}
	return err
}
