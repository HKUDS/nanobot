package agents

import (
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func TestGetContextWindowSize_ConfigOverride(t *testing.T) {
	size := getContextWindowSize(50000)
	if size != 50000 {
		t.Errorf("expected config override 50000, got %d", size)
	}
}

func TestGetContextWindowSize_Default(t *testing.T) {
	size := getContextWindowSize(0)
	if size != defaultContextWindow {
		t.Errorf("expected default %d, got %d", defaultContextWindow, size)
	}
}

func TestShouldCompact_BelowThreshold(t *testing.T) {
	req := types.CompletionRequest{
		Input: []types.Message{
			{
				Role: "user",
				Items: []types.CompletionItem{
					{Content: &mcp.Content{Type: "text", Text: "hello"}},
				},
			},
		},
	}

	if shouldCompact(req, 128_000) {
		t.Error("should not compact small input")
	}
}

func TestShouldCompact_ZeroContextWindow(t *testing.T) {
	req := types.CompletionRequest{
		Input: []types.Message{
			{
				Role: "user",
				Items: []types.CompletionItem{
					{Content: &mcp.Content{Type: "text", Text: "hello"}},
				},
			},
		},
	}

	if shouldCompact(req, 0) {
		t.Error("should not compact with zero context window")
	}
}

func TestShouldCompact_NegativeContextWindow(t *testing.T) {
	req := types.CompletionRequest{}
	if shouldCompact(req, -1) {
		t.Error("should not compact with negative context window")
	}
}

func TestShouldCompact_EmptyInput(t *testing.T) {
	req := types.CompletionRequest{}
	if shouldCompact(req, 128_000) {
		t.Error("should not compact empty input")
	}
}

func TestIsCompactionSummary_True(t *testing.T) {
	msg := types.Message{
		Items: []types.CompletionItem{
			{
				Content: &mcp.Content{
					Type: "text",
					Text: "summary",
					Meta: map[string]any{
						compactionSummaryMetaKey: true,
					},
				},
			},
		},
	}

	if !IsCompactionSummary(msg) {
		t.Error("expected IsCompactionSummary to return true")
	}
}

func TestIsCompactionSummary_False(t *testing.T) {
	msg := types.Message{
		Items: []types.CompletionItem{
			{
				Content: &mcp.Content{
					Type: "text",
					Text: "normal message",
				},
			},
		},
	}

	if IsCompactionSummary(msg) {
		t.Error("expected IsCompactionSummary to return false for normal message")
	}
}

func TestIsCompactionSummary_EmptyMessage(t *testing.T) {
	msg := types.Message{}
	if IsCompactionSummary(msg) {
		t.Error("expected IsCompactionSummary to return false for empty message")
	}
}

func TestIsCompactionSummary_NilContent(t *testing.T) {
	msg := types.Message{
		Items: []types.CompletionItem{
			{Content: nil},
		},
	}
	if IsCompactionSummary(msg) {
		t.Error("expected IsCompactionSummary to return false for nil content")
	}
}

func TestSplitHistoryAndNewInput_Basic(t *testing.T) {
	fullInput := []types.Message{
		{ID: "msg-1", Role: "user"},
		{ID: "msg-2", Role: "assistant"},
		{ID: "msg-3", Role: "user"},
		{ID: "msg-4", Role: "assistant"},
		{ID: "msg-5", Role: "user"},
	}

	currentReqInput := []types.Message{
		{ID: "msg-5", Role: "user"},
	}

	history, newInput := splitHistoryAndNewInput(fullInput, currentReqInput)

	if len(history) != 4 {
		t.Errorf("expected 4 history messages, got %d", len(history))
	}
	if len(newInput) != 1 {
		t.Errorf("expected 1 new input message, got %d", len(newInput))
	}
	if newInput[0].ID != "msg-5" {
		t.Errorf("expected new input first message ID to be msg-5, got %s", newInput[0].ID)
	}
}

func TestSplitHistoryAndNewInput_EmptyCurrentRequest(t *testing.T) {
	fullInput := []types.Message{
		{ID: "msg-1"},
		{ID: "msg-2"},
	}

	history, newInput := splitHistoryAndNewInput(fullInput, nil)

	if len(history) != 2 {
		t.Errorf("expected 2 history messages, got %d", len(history))
	}
	if len(newInput) != 0 {
		t.Errorf("expected 0 new input messages, got %d", len(newInput))
	}
}

func TestSplitHistoryAndNewInput_AllNew(t *testing.T) {
	fullInput := []types.Message{
		{ID: "msg-1"},
	}

	currentReqInput := []types.Message{
		{ID: "msg-1"},
	}

	history, newInput := splitHistoryAndNewInput(fullInput, currentReqInput)

	if len(history) != 0 {
		t.Errorf("expected 0 history messages, got %d", len(history))
	}
	if len(newInput) != 1 {
		t.Errorf("expected 1 new input message, got %d", len(newInput))
	}
}

func TestSplitHistoryAndNewInput_NotFound(t *testing.T) {
	fullInput := []types.Message{
		{ID: "msg-1"},
		{ID: "msg-2"},
	}

	currentReqInput := []types.Message{
		{ID: "msg-99"},
	}

	history, newInput := splitHistoryAndNewInput(fullInput, currentReqInput)

	if len(history) != 2 {
		t.Errorf("expected 2 history messages (all input), got %d", len(history))
	}
	if len(newInput) != 0 {
		t.Errorf("expected 0 new input messages, got %d", len(newInput))
	}
}

func TestBuildTranscript_Basic(t *testing.T) {
	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: "What is the weather?"}},
			},
		},
		{
			Role: "assistant",
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: "Let me check."}},
			},
		},
	}

	transcript := buildTranscript(messages)

	if transcript == "" {
		t.Error("expected non-empty transcript")
	}
	if len(transcript) < 20 {
		t.Errorf("transcript too short: %q", transcript)
	}
}

func TestBuildTranscript_WithToolCalls(t *testing.T) {
	messages := []types.Message{
		{
			Role: "assistant",
			Items: []types.CompletionItem{
				{
					ToolCall: &types.ToolCall{
						Name:      "weather",
						Arguments: `{"city": "London"}`,
					},
				},
			},
		},
	}

	transcript := buildTranscript(messages)

	if transcript == "" {
		t.Error("expected non-empty transcript")
	}
}

func TestBuildTranscript_WithToolResults(t *testing.T) {
	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{
					ToolCallResult: &types.ToolCallResult{
						CallID: "call-1",
						Output: types.CallResult{
							Content: []mcp.Content{
								{Type: "text", Text: "Sunny, 22C"},
							},
						},
					},
				},
			},
		},
	}

	transcript := buildTranscript(messages)

	if transcript == "" {
		t.Error("expected non-empty transcript")
	}
}

func TestBuildTranscript_TruncatesLongResults(t *testing.T) {
	longText := ""
	for i := 0; i < 200; i++ {
		longText += "This is a very long tool result. "
	}

	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{
					ToolCallResult: &types.ToolCallResult{
						CallID: "call-1",
						Output: types.CallResult{
							Content: []mcp.Content{
								{Type: "text", Text: longText},
							},
						},
					},
				},
			},
		},
	}

	transcript := buildTranscript(messages)

	// Transcript should be shorter than the original text due to truncation
	if len(transcript) > len(longText) {
		t.Errorf("expected truncated transcript, got length %d (original %d)", len(transcript), len(longText))
	}
}

func TestExtractTextFromResponse(t *testing.T) {
	resp := &types.CompletionResponse{
		Output: types.Message{
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: "First part."}},
				{Content: &mcp.Content{Type: "text", Text: "Second part."}},
			},
		},
	}

	text := extractTextFromResponse(resp)
	if text != "First part.\nSecond part." {
		t.Errorf("unexpected text: %q", text)
	}
}

func TestExtractTextFromResponse_Nil(t *testing.T) {
	text := extractTextFromResponse(nil)
	if text != "" {
		t.Errorf("expected empty string for nil response, got %q", text)
	}
}

func TestExtractTextFromResponse_NoTextItems(t *testing.T) {
	resp := &types.CompletionResponse{
		Output: types.Message{
			Items: []types.CompletionItem{
				{ToolCall: &types.ToolCall{Name: "test"}},
			},
		},
	}

	text := extractTextFromResponse(resp)
	if text != "" {
		t.Errorf("expected empty string for non-text items, got %q", text)
	}
}
