package sampling

import (
	"context"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type fakeCompleter struct {
	lastReq types.CompletionRequest
}

func (f *fakeCompleter) Complete(_ context.Context, req types.CompletionRequest, _ ...types.CompletionOptions) (*types.CompletionResponse, error) {
	f.lastReq = req
	return &types.CompletionResponse{
		Output: types.Message{
			ID:   "out",
			Role: "assistant",
			Items: []types.CompletionItem{
				{
					ID: "item1",
					Content: &mcp.Content{
						Type: "text",
						Text: "ok",
					},
				},
			},
		},
	}, nil
}

func TestSamplePreservesAttachmentHiddenMessageBoundary(t *testing.T) {
	complete := &fakeCompleter{}
	s := NewSampler(complete)

	ctx := types.WithConfig(context.Background(), types.Config{
		Agents: map[string]types.Agent{
			"test-agent": {
				HookAgent: types.HookAgent{
					Model: "test-model",
				},
			},
		},
	})

	_, err := s.Sample(ctx, mcp.CreateMessageRequest{
		ModelPreferences: mcp.ModelPreferences{
			Hints: []mcp.ModelHint{{Name: "test-agent"}},
		},
		Messages: []mcp.SamplingMessage{
			{
				Role: "user",
				Content: []mcp.Content{
					{Type: "text", Text: "hello"},
				},
			},
			{
				Role: "user",
				Content: []mcp.Content{
					{
						Type: "text",
						Text: "hidden attachment instruction",
						Meta: map[string]any{
							types.AttachmentMetaKey: true,
						},
					},
				},
			},
		},
	})
	if err != nil {
		t.Fatalf("Sample returned error: %v", err)
	}

	if len(complete.lastReq.Input) != 2 {
		t.Fatalf("expected 2 separate user messages, got %d", len(complete.lastReq.Input))
	}
	if complete.lastReq.Input[0].Items[0].Content.Text != "hello" {
		t.Fatalf("unexpected first message text: %q", complete.lastReq.Input[0].Items[0].Content.Text)
	}
	if complete.lastReq.Input[1].Items[0].Content.Text != "hidden attachment instruction" {
		t.Fatalf("unexpected second message text: %q", complete.lastReq.Input[1].Items[0].Content.Text)
	}
}
