package agents

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

const maxToolResultSize = 50 * 1024 // 50 KiB

var sanitizeRe = regexp.MustCompile(`[^a-zA-Z0-9_\-.]`)

const sessionsDir = "sessions"

// hasSkipTruncation returns true if any content item has the skip-truncation meta key set.
func hasSkipTruncation(content []mcp.Content) bool {
	for _, c := range content {
		if v, ok := c.Meta[types.SkipTruncationMetaKey].(bool); ok && v {
			return true
		}
	}
	return false
}

func truncateToolResult(ctx context.Context, toolName, callID string, msg *types.Message) *types.Message {
	if msg == nil || len(msg.Items) == 0 {
		return msg
	}

	result := msg.Items[0].ToolCallResult
	if result == nil {
		return msg
	}

	content := result.Output.Content
	if len(content) == 0 {
		return msg
	}

	if hasSkipTruncation(content) {
		return msg
	}

	size := contentSize(content)
	if size <= maxToolResultSize {
		return msg
	}

	// Determine file extension
	ext := ".txt"
	for _, c := range content {
		if c.Type != "" && c.Type != "text" {
			ext = ".json"
			break
		}
	}

	// Build absolute file path (store under the session's working directory)
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	fileName := sanitizePathComponent(toolName) + "-" + sanitizePathComponent(callID) + ext
	filePath := filepath.Join(sessionsDir, sessionID, "truncated-outputs", fileName)
	if cwd, err := os.Getwd(); err == nil {
		filePath = filepath.Join(cwd, filePath)
	}

	writeErr := writeFullResult(content, filePath)
	truncated := buildTruncatedContent(content, maxToolResultSize, filePath)
	if writeErr != nil {
		slog.Error("failed to write truncated tool result", "path", filePath, "error", writeErr)

		noticePart := mcp.Content{
			Type: "text",
			Text: fmt.Sprintf("Note: failed to persist full tool output to %s: %v. Only truncated output is available.", filePath, writeErr),
		}
		truncated = append([]mcp.Content{noticePart}, truncated...)
	}

	newOutput := result.Output
	newOutput.Content = truncated

	return &types.Message{
		ID:   msg.ID,
		Role: msg.Role,
		Items: []types.CompletionItem{
			{
				ID: msg.Items[0].ID,
				ToolCallResult: &types.ToolCallResult{
					CallID: result.CallID,
					Output: newOutput,
				},
			},
		},
	}
}

func contentSize(content []mcp.Content) int {
	total := 0
	for _, c := range content {
		switch c.Type {
		case "text", "":
			total += len(c.Text)
		case "image", "audio":
			total += len(c.Data)
		case "resource":
			if c.Resource != nil {
				total += len(c.Resource.Text) + len(c.Resource.Blob)
			}
		default:
			data, err := json.Marshal(c)
			if err == nil {
				total += len(data)
			}
		}
	}
	return total
}

func writeFullResult(content []mcp.Content, filePath string) error {
	if err := os.MkdirAll(filepath.Dir(filePath), 0700); err != nil {
		return err
	}

	allText := true
	for _, c := range content {
		if c.Type != "" && c.Type != "text" {
			allText = false
			break
		}
	}

	if allText {
		var sb strings.Builder
		for i, c := range content {
			if i > 0 {
				sb.WriteString("\n")
			}
			sb.WriteString(c.Text)
		}
		return os.WriteFile(filePath, []byte(sb.String()), 0600)
	}

	data, err := json.MarshalIndent(content, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filePath, data, 0600)
}

func buildTruncatedContent(content []mcp.Content, budget int, filePath string) []mcp.Content {
	suffix := fmt.Sprintf("\n\n[Truncated: full output available at %s]", filePath)
	remaining := budget - len(suffix)
	if remaining < 0 {
		remaining = 0
	}

	var result []mcp.Content

	for _, c := range content {
		if remaining <= 0 {
			break
		}

		switch c.Type {
		case "text", "":
			text := c.Text
			if len(text) > remaining {
				text = text[:remaining]
			}
			result = append(result, mcp.Content{
				Type: "text",
				Text: text,
			})
			remaining -= len(text)
		default:
			note := fmt.Sprintf("[%s content written to %s]", c.Type, filePath)
			result = append(result, mcp.Content{
				Type: "text",
				Text: note,
			})
			remaining -= len(note)
		}
	}

	result = append(result, mcp.Content{
		Type: "text",
		Text: suffix,
	})

	return result
}

func sanitizePathComponent(s string) string {
	s = sanitizeRe.ReplaceAllString(s, "_")
	s = strings.TrimLeft(s, ".")
	if len(s) > 100 {
		s = s[:100]
	}
	if s == "" {
		s = "unnamed"
	}
	return s
}
