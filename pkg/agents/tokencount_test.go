package agents

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/color"
	"image/jpeg"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func TestEstimateTokens_BasicMessages(t *testing.T) {
	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: "Hello, how are you?"}},
			},
		},
		{
			Role: "assistant",
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: "I'm doing well, thank you!"}},
			},
		},
	}

	tokens := estimateTokens(messages, "", nil)
	if tokens <= 0 {
		t.Errorf("expected positive token count, got %d", tokens)
	}
	// Two short messages should be a small number of tokens
	if tokens > 100 {
		t.Errorf("expected < 100 tokens for short messages, got %d", tokens)
	}
}

func TestEstimateTokens_WithSystemPrompt(t *testing.T) {
	tokensWithout := estimateTokens(nil, "", nil)
	tokensWith := estimateTokens(nil, "You are a helpful assistant.", nil)
	if tokensWith <= tokensWithout {
		t.Errorf("expected more tokens with system prompt: without=%d, with=%d", tokensWithout, tokensWith)
	}
}

func TestEstimateTokens_WithTools(t *testing.T) {
	tools := []types.ToolUseDefinition{
		{
			Name:        "search",
			Description: "Search the web for information",
			Parameters:  []byte(`{"type":"object","properties":{"query":{"type":"string"}}}`),
		},
	}

	tokensWithout := estimateTokens(nil, "", nil)
	tokensWith := estimateTokens(nil, "", tools)
	if tokensWith <= tokensWithout {
		t.Errorf("expected more tokens with tools: without=%d, with=%d", tokensWithout, tokensWith)
	}
}

func TestEstimateTokens_LargeInput(t *testing.T) {
	longText := strings.Repeat("This is a test sentence. ", 1000)
	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{Content: &mcp.Content{Type: "text", Text: longText}},
			},
		},
	}

	tokens := estimateTokens(messages, "", nil)
	// A large input should produce a significant number of tokens
	if tokens < 1000 {
		t.Errorf("expected > 1000 tokens for large input, got %d", tokens)
	}
}

func TestEstimateTokens_WithToolCalls(t *testing.T) {
	messages := []types.Message{
		{
			Role: "assistant",
			Items: []types.CompletionItem{
				{
					ToolCall: &types.ToolCall{
						Name:      "search",
						Arguments: `{"query": "test"}`,
						CallID:    "call-1",
					},
				},
			},
		},
	}

	tokens := estimateTokens(messages, "", nil)
	if tokens <= 0 {
		t.Errorf("expected positive token count for tool calls, got %d", tokens)
	}
}

func TestEstimateTokens_WithToolResults(t *testing.T) {
	messages := []types.Message{
		{
			Role: "user",
			Items: []types.CompletionItem{
				{
					ToolCallResult: &types.ToolCallResult{
						CallID: "call-1",
						Output: types.CallResult{
							Content: []mcp.Content{
								{Type: "text", Text: "Search results here"},
							},
						},
					},
				},
			},
		},
	}

	tokens := estimateTokens(messages, "", nil)
	if tokens <= 0 {
		t.Errorf("expected positive token count for tool results, got %d", tokens)
	}
}

func TestCountTokens_EmptyString(t *testing.T) {
	tokens := countTokens("")
	if tokens != 0 {
		t.Errorf("expected 0 tokens for empty string, got %d", tokens)
	}
}

func TestCountTokens_KnownString(t *testing.T) {
	// "hello world" should produce a small number of tokens
	tokens := countTokens("hello world")
	if tokens < 1 || tokens > 5 {
		t.Errorf("expected 1-5 tokens for 'hello world', got %d", tokens)
	}
}

// createTestJPEG generates a base64-encoded JPEG image of the given dimensions.
func createTestJPEG(t *testing.T, w, h int) string {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := range h {
		for x := range w {
			img.Set(x, y, color.RGBA{R: 255, G: 0, B: 0, A: 255})
		}
	}
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, nil); err != nil {
		t.Fatalf("failed to encode test JPEG (%dx%d): %v", w, h, err)
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes())
}

func TestEstimateImageTokens(t *testing.T) {
	tests := []struct {
		name     string
		data     string
		expected int
	}{
		{
			name:     "Small",
			data:     createTestJPEG(t, 100, 100),
			expected: 13, // round(10000 / 750) = 13
		},
		{
			name:     "ExactMaxEdge",
			data:     createTestJPEG(t, 1568, 1000),
			expected: 2091, // no resize, round(1568000 / 750) = 2091
		},
		{
			name:     "SquareAtMax",
			data:     createTestJPEG(t, 1568, 1568),
			expected: 3278, // no resize, round(2458624 / 750) = 3278
		},
		{
			name:     "LargeNeedsResize",
			data:     createTestJPEG(t, 4000, 3000),
			expected: 2459, // scale=1568/4000=0.392 -> 1568x1176, round(1843968 / 750) = 2459
		},
		{
			name:     "TallPortrait",
			data:     createTestJPEG(t, 1000, 3000),
			expected: 1091, // scale=1568/3000=0.5227 -> 522x1568, round(818496 / 750) = 1091
		},
		{
			name:     "Tiny",
			data:     createTestJPEG(t, 1, 1),
			expected: 0, // round(1 / 750) = 0
		},
		{
			name:     "InvalidBase64",
			data:     "!!!not-valid-base64!!!",
			expected: 1600, // fallback: base64 decode fails
		},
		{
			name:     "NotAnImage",
			data:     base64.StdEncoding.EncodeToString([]byte("hello world")),
			expected: 1600, // fallback: image.DecodeConfig fails
		},
		{
			name:     "EmptyString",
			data:     "",
			expected: 1600, // fallback: empty data, DecodeConfig fails
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := estimateImageTokens(tt.data)
			if got != tt.expected {
				t.Errorf("estimateImageTokens() = %d, want %d", got, tt.expected)
			}
		})
	}
}
