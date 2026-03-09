package tools

import (
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/types"
)

func testConfig() types.Config {
	return types.Config{
		Agents: map[string]types.Agent{
			"test-agent": {
				HookAgent: types.HookAgent{
					MaxTokens: 1234,
				},
			},
		},
	}
}

func TestConvertToSampleRequestWithFileAttachments(t *testing.T) {
	s := &Service{}

	req, err := s.convertToSampleRequest(testConfig(), "test-agent", map[string]any{
		"prompt": "Check the attached files",
		"attachments": []any{
			map[string]any{"url": "file:///notes/todo.md"},
			map[string]any{"url": "file:///notes/todo.md"},
			map[string]any{"url": "file:///docs/spec%20draft.md"},
		},
	})
	if err != nil {
		t.Fatalf("convertToSampleRequest returned error: %v", err)
	}

	if len(req.Messages) != 2 {
		t.Fatalf("expected 2 messages (prompt+preview and hidden attachment context), got %d", len(req.Messages))
	}

	first := req.Messages[0]
	if len(first.Content) != 3 {
		t.Fatalf("expected prompt message to include text + 2 previews, got %d items", len(first.Content))
	}
	if first.Content[0].Type != "text" || first.Content[0].Text != "Check the attached files" {
		t.Fatalf("unexpected first content item: %#v", first.Content[0])
	}
	if first.Content[1].Type != "resource_link" || first.Content[1].URI != "file:///notes/todo.md" {
		t.Fatalf("unexpected first attachment preview: %#v", first.Content[1])
	}
	if first.Content[2].Type != "resource_link" || first.Content[2].URI != "file:///docs/spec%20draft.md" {
		t.Fatalf("unexpected second attachment preview: %#v", first.Content[2])
	}

	second := req.Messages[1]
	if len(second.Content) != 1 || second.Content[0].Type != "text" {
		t.Fatalf("expected hidden attachment text message, got %#v", second.Content)
	}
	if second.Content[0].Meta == nil || second.Content[0].Meta[types.AttachmentMetaKey] != true {
		t.Fatalf("expected attachment meta key %q=true, got %#v", types.AttachmentMetaKey, second.Content[0].Meta)
	}
	if !strings.Contains(second.Content[0].Text, `"notes/todo.md"`) ||
		!strings.Contains(second.Content[0].Text, `"docs/spec draft.md"`) {
		t.Fatalf("expected hidden message to include decoded paths, got: %q", second.Content[0].Text)
	}
}

func TestConvertToSampleRequestDataAttachmentStillInlined(t *testing.T) {
	s := &Service{}

	req, err := s.convertToSampleRequest(testConfig(), "test-agent", map[string]any{
		"prompt": "Review this image",
		"attachments": []any{
			map[string]any{
				"url":      "data:image/png;base64,ZmFrZQ==",
				"name":     "test.png",
				"mimeType": "image/png",
			},
		},
	})
	if err != nil {
		t.Fatalf("convertToSampleRequest returned error: %v", err)
	}

	if len(req.Messages) != 2 {
		t.Fatalf("expected 2 messages (prompt + data attachment), got %d", len(req.Messages))
	}

	dataMsg := req.Messages[1]
	if len(dataMsg.Content) != 1 {
		t.Fatalf("expected 1 content item for data attachment, got %d", len(dataMsg.Content))
	}
	if dataMsg.Content[0].Type != "image" || dataMsg.Content[0].Data != "ZmFrZQ==" {
		t.Fatalf("unexpected data attachment item: %#v", dataMsg.Content[0])
	}
}

func TestConvertToSampleRequestRejectsInvalidAttachmentURL(t *testing.T) {
	s := &Service{}

	_, err := s.convertToSampleRequest(testConfig(), "test-agent", map[string]any{
		"prompt": "Check this",
		"attachments": []any{
			map[string]any{"url": "https://example.com/file.pdf"},
		},
	})
	if err == nil {
		t.Fatal("expected error for invalid attachment URL, got nil")
	}
	if !strings.Contains(err.Error(), "only data URI and file:/// URIs are supported") {
		t.Fatalf("unexpected error: %v", err)
	}
}
