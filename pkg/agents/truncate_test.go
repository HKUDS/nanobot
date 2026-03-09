package agents

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func makeTextContent(text string) []mcp.Content {
	return []mcp.Content{{Type: "text", Text: text}}
}

func makeToolResultMessage(callID string, content []mcp.Content, isError bool) *types.Message {
	return &types.Message{
		ID:   "msg-1",
		Role: "user",
		Items: []types.CompletionItem{
			{
				ID: "item-1",
				ToolCallResult: &types.ToolCallResult{
					CallID: callID,
					Output: types.CallResult{
						Content: content,
						IsError: isError,
					},
				},
			},
		},
	}
}

func contextWithSessionID(t *testing.T, sessionID string) context.Context {
	t.Helper()

	serverSession, err := mcp.NewExistingServerSession(
		context.Background(),
		mcp.SessionState{ID: sessionID},
		mcp.MessageHandlerFunc(func(context.Context, mcp.Message) {}),
	)
	if err != nil {
		t.Fatalf("failed to create test session: %v", err)
	}
	t.Cleanup(func() {
		serverSession.Close(false)
	})
	return mcp.WithSession(context.Background(), serverSession.GetSession())
}

// --- contentSize tests ---

func TestContentSize_TextOnly(t *testing.T) {
	content := []mcp.Content{
		{Type: "text", Text: "hello"},
		{Type: "text", Text: "world"},
	}
	if got := contentSize(content); got != 10 {
		t.Errorf("contentSize = %d, want 10", got)
	}
}

func TestContentSize_EmptyType(t *testing.T) {
	content := []mcp.Content{
		{Text: "abc"},
	}
	if got := contentSize(content); got != 3 {
		t.Errorf("contentSize = %d, want 3", got)
	}
}

func TestContentSize_Image(t *testing.T) {
	content := []mcp.Content{
		{Type: "image", Data: "base64data"},
	}
	if got := contentSize(content); got != 10 {
		t.Errorf("contentSize = %d, want 10", got)
	}
}

func TestContentSize_Audio(t *testing.T) {
	content := []mcp.Content{
		{Type: "audio", Data: "audiodata123"},
	}
	if got := contentSize(content); got != 12 {
		t.Errorf("contentSize = %d, want 12", got)
	}
}

func TestContentSize_Resource(t *testing.T) {
	content := []mcp.Content{
		{Type: "resource", Resource: &mcp.EmbeddedResource{
			Text: "some text",
			Blob: "blob",
		}},
	}
	if got := contentSize(content); got != 13 {
		t.Errorf("contentSize = %d, want 13", got)
	}
}

func TestContentSize_ResourceNil(t *testing.T) {
	content := []mcp.Content{
		{Type: "resource"},
	}
	if got := contentSize(content); got != 0 {
		t.Errorf("contentSize = %d, want 0", got)
	}
}

func TestContentSize_UnknownType(t *testing.T) {
	content := []mcp.Content{
		{Type: "custom_type", Text: "ignored by switch"},
	}
	size := contentSize(content)
	// Should fall through to json.Marshal
	data, _ := json.Marshal(content[0])
	if size != len(data) {
		t.Errorf("contentSize = %d, want %d (json marshal length)", size, len(data))
	}
}

func TestContentSize_Mixed(t *testing.T) {
	content := []mcp.Content{
		{Type: "text", Text: "hello"},
		{Type: "image", Data: "imgdata"},
	}
	if got := contentSize(content); got != 12 {
		t.Errorf("contentSize = %d, want 12", got)
	}
}

func TestContentSize_Empty(t *testing.T) {
	if got := contentSize(nil); got != 0 {
		t.Errorf("contentSize = %d, want 0", got)
	}
}

// --- sanitizePathComponent tests ---

func TestSanitizePathComponent_Clean(t *testing.T) {
	if got := sanitizePathComponent("hello-world_1.0"); got != "hello-world_1.0" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "hello-world_1.0")
	}
}

func TestSanitizePathComponent_SpecialChars(t *testing.T) {
	if got := sanitizePathComponent("foo/bar:baz@qux"); got != "foo_bar_baz_qux" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "foo_bar_baz_qux")
	}
}

func TestSanitizePathComponent_LeadingDots(t *testing.T) {
	if got := sanitizePathComponent("..hidden"); got != "hidden" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "hidden")
	}
}

func TestSanitizePathComponent_AllDots(t *testing.T) {
	if got := sanitizePathComponent("..."); got != "unnamed" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "unnamed")
	}
}

func TestSanitizePathComponent_Empty(t *testing.T) {
	if got := sanitizePathComponent(""); got != "unnamed" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "unnamed")
	}
}

func TestSanitizePathComponent_AllSpecial(t *testing.T) {
	if got := sanitizePathComponent("@#$%"); got != "____" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "____")
	}
}

func TestSanitizePathComponent_LongString(t *testing.T) {
	long := strings.Repeat("a", 200)
	got := sanitizePathComponent(long)
	if len(got) != 100 {
		t.Errorf("sanitizePathComponent length = %d, want 100", len(got))
	}
}

func TestSanitizePathComponent_Spaces(t *testing.T) {
	if got := sanitizePathComponent("my tool name"); got != "my_tool_name" {
		t.Errorf("sanitizePathComponent = %q, want %q", got, "my_tool_name")
	}
}

// --- writeFullResult tests ---

func TestWriteFullResult_AllText(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "output.txt")

	content := []mcp.Content{
		{Type: "text", Text: "line one"},
		{Type: "text", Text: "line two"},
	}

	if err := writeFullResult(content, path); err != nil {
		t.Fatalf("writeFullResult error: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile error: %v", err)
	}

	expected := "line one\nline two"
	if string(data) != expected {
		t.Errorf("file content = %q, want %q", string(data), expected)
	}
}

func TestWriteFullResult_SingleText(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "output.txt")

	content := []mcp.Content{
		{Type: "text", Text: "only one"},
	}

	if err := writeFullResult(content, path); err != nil {
		t.Fatalf("writeFullResult error: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile error: %v", err)
	}

	if string(data) != "only one" {
		t.Errorf("file content = %q, want %q", string(data), "only one")
	}
}

func TestWriteFullResult_MixedContent(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "output.json")

	content := []mcp.Content{
		{Type: "text", Text: "some text"},
		{Type: "image", Data: "base64img"},
	}

	if err := writeFullResult(content, path); err != nil {
		t.Fatalf("writeFullResult error: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile error: %v", err)
	}

	// Should be valid JSON
	var parsed []mcp.Content
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("JSON unmarshal error: %v", err)
	}

	if len(parsed) != 2 {
		t.Fatalf("parsed length = %d, want 2", len(parsed))
	}
	if parsed[0].Text != "some text" {
		t.Errorf("parsed[0].Text = %q, want %q", parsed[0].Text, "some text")
	}
	if parsed[1].Data != "base64img" {
		t.Errorf("parsed[1].Data = %q, want %q", parsed[1].Data, "base64img")
	}
}

func TestWriteFullResult_CreatesDirectories(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "a", "b", "c", "output.txt")

	content := []mcp.Content{
		{Type: "text", Text: "deep"},
	}

	if err := writeFullResult(content, path); err != nil {
		t.Fatalf("writeFullResult error: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile error: %v", err)
	}

	if string(data) != "deep" {
		t.Errorf("file content = %q, want %q", string(data), "deep")
	}
}

// --- buildTruncatedContent tests ---

func TestBuildTruncatedContent_TruncatesLongText(t *testing.T) {
	filePath := "/tmp/test/output.txt"
	bigText := strings.Repeat("x", 1000)
	content := []mcp.Content{
		{Type: "text", Text: bigText},
	}

	result := buildTruncatedContent(content, 200, filePath)

	// Last item should be the truncation notice
	last := result[len(result)-1]
	if !strings.Contains(last.Text, "[Truncated: full output available at") {
		t.Errorf("last item should be truncation notice, got %q", last.Text)
	}

	// Total size of all text should be around the budget
	totalSize := 0
	for _, c := range result {
		totalSize += len(c.Text)
	}
	if totalSize > 200+100 { // some slack for the notice
		t.Errorf("total truncated size = %d, expected around 200", totalSize)
	}

	// The text content should be truncated
	if len(result[0].Text) >= 1000 {
		t.Errorf("text was not truncated: length = %d", len(result[0].Text))
	}
}

func TestBuildTruncatedContent_NonTextReplaced(t *testing.T) {
	filePath := "/tmp/test/output.json"
	content := []mcp.Content{
		{Type: "text", Text: "hello"},
		{Type: "image", Data: strings.Repeat("x", 1000)},
	}

	result := buildTruncatedContent(content, 500, filePath)

	// Should have: text item, image replacement note, truncation notice
	foundImageNote := false
	for _, c := range result {
		if strings.Contains(c.Text, "[image content written to") {
			foundImageNote = true
		}
	}
	if !foundImageNote {
		t.Error("expected image replacement note in truncated content")
	}
}

func TestBuildTruncatedContent_MultipleTextItems(t *testing.T) {
	filePath := "/tmp/test/output.txt"
	content := []mcp.Content{
		{Type: "text", Text: strings.Repeat("a", 100)},
		{Type: "text", Text: strings.Repeat("b", 100)},
		{Type: "text", Text: strings.Repeat("c", 100)},
	}

	// Budget small enough to cut off mid-way
	result := buildTruncatedContent(content, 200, filePath)

	// Should have at least one text item and the truncation notice
	if len(result) < 2 {
		t.Fatalf("expected at least 2 items, got %d", len(result))
	}

	last := result[len(result)-1]
	if !strings.Contains(last.Text, "[Truncated:") {
		t.Errorf("last item should be truncation notice, got %q", last.Text)
	}
}

func TestBuildTruncatedContent_DropsItemsAfterBudget(t *testing.T) {
	filePath := "/tmp/test/output.txt"
	content := []mcp.Content{
		{Type: "text", Text: strings.Repeat("a", 500)},
		{Type: "text", Text: "should not appear"},
	}

	// Budget smaller than first item
	result := buildTruncatedContent(content, 200, filePath)

	// Should only have the first (truncated) text and the notice
	if len(result) != 2 {
		t.Fatalf("expected 2 items, got %d", len(result))
	}

	if strings.Contains(result[0].Text, "should not appear") {
		t.Error("second text item should have been dropped")
	}
}

// --- truncateToolResult integration tests ---

func TestTruncateToolResult_NilMessage(t *testing.T) {
	ctx := context.Background()
	result := truncateToolResult(ctx, "tool", "call1", nil)
	if result != nil {
		t.Error("expected nil result for nil input")
	}
}

func TestTruncateToolResult_EmptyItems(t *testing.T) {
	ctx := context.Background()
	msg := &types.Message{Items: []types.CompletionItem{}}
	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result != msg {
		t.Error("expected same message returned for empty items")
	}
}

func TestTruncateToolResult_NoToolCallResult(t *testing.T) {
	ctx := context.Background()
	msg := &types.Message{
		Items: []types.CompletionItem{
			{ID: "item-1"},
		},
	}
	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result != msg {
		t.Error("expected same message returned when no ToolCallResult")
	}
}

func TestTruncateToolResult_SmallErrorResult(t *testing.T) {
	ctx := context.Background()
	msg := makeToolResultMessage("call1", makeTextContent("error details"), true)
	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result != msg {
		t.Error("expected same message returned for small error results")
	}
}

func TestTruncateToolResult_LargeErrorResult(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	ctx := context.Background()
	bigError := strings.Repeat("error line\n", maxToolResultSize/10)
	msg := makeToolResultMessage("call1", makeTextContent(bigError), true)

	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result == msg {
		t.Fatal("expected large error result to be truncated")
	}

	// IsError should be preserved
	tcr := result.Items[0].ToolCallResult
	if !tcr.Output.IsError {
		t.Error("truncated error result should preserve IsError=true")
	}
}

func TestTruncateToolResult_EmptyContent(t *testing.T) {
	ctx := context.Background()
	msg := makeToolResultMessage("call1", nil, false)
	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result != msg {
		t.Error("expected same message returned for empty content")
	}
}

func TestTruncateToolResult_SmallContent(t *testing.T) {
	ctx := context.Background()
	msg := makeToolResultMessage("call1", makeTextContent("small"), false)
	result := truncateToolResult(ctx, "tool", "call1", msg)
	if result != msg {
		t.Error("expected same message returned for small content")
	}
}

func TestTruncateToolResult_LargeTextContent(t *testing.T) {
	// Change to temp dir so .nanobot is created in a clean location
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	ctx := contextWithSessionID(t, "default")
	bigText := strings.Repeat("x", maxToolResultSize+1000)
	msg := makeToolResultMessage("call1", makeTextContent(bigText), false)

	result := truncateToolResult(ctx, "my-tool", "call1", msg)

	// Should be a different message
	if result == msg {
		t.Fatal("expected truncated message, got original")
	}

	// Should preserve message metadata
	if result.ID != msg.ID {
		t.Errorf("ID = %q, want %q", result.ID, msg.ID)
	}
	if result.Role != msg.Role {
		t.Errorf("Role = %q, want %q", result.Role, msg.Role)
	}

	// Should have tool call result
	if len(result.Items) != 1 {
		t.Fatalf("Items length = %d, want 1", len(result.Items))
	}
	tcr := result.Items[0].ToolCallResult
	if tcr == nil {
		t.Fatal("ToolCallResult is nil")
	}
	if tcr.CallID != "call1" {
		t.Errorf("CallID = %q, want %q", tcr.CallID, "call1")
	}

	// Last content item should be truncation notice
	content := tcr.Output.Content
	last := content[len(content)-1]
	if !strings.Contains(last.Text, "[Truncated: full output available at") {
		t.Errorf("expected truncation notice, got %q", last.Text)
	}

	// IsError should NOT be set
	if tcr.Output.IsError {
		t.Error("truncated result should not be marked as error")
	}

	// File should exist with full content in the session working directory
	filePath := filepath.Join("sessions", "default", "truncated-outputs", "my-tool-call1.txt")
	data, err := os.ReadFile(filePath)
	if err != nil {
		t.Fatalf("failed to read output file: %v", err)
	}
	if string(data) != bigText {
		t.Errorf("file content length = %d, want %d", len(data), len(bigText))
	}
}

func TestTruncateToolResult_MixedContentUsesJSON(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	ctx := contextWithSessionID(t, "default")
	content := []mcp.Content{
		{Type: "text", Text: strings.Repeat("a", maxToolResultSize)},
		{Type: "image", Data: strings.Repeat("b", 1000)},
	}
	msg := makeToolResultMessage("call2", content, false)

	result := truncateToolResult(ctx, "img-tool", "call2", msg)
	if result == msg {
		t.Fatal("expected truncated message, got original")
	}

	// Should use .json extension in the session working directory
	filePath := filepath.Join("sessions", "default", "truncated-outputs", "img-tool-call2.json")
	data, err := os.ReadFile(filePath)
	if err != nil {
		t.Fatalf("failed to read output file: %v", err)
	}

	// Should be valid JSON array of content
	var parsed []mcp.Content
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("file is not valid JSON: %v", err)
	}
	if len(parsed) != 2 {
		t.Errorf("parsed content length = %d, want 2", len(parsed))
	}
}

func TestTruncateToolResult_DoesNotMutateOriginal(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	ctx := context.Background()
	originalText := strings.Repeat("z", maxToolResultSize+500)
	msg := makeToolResultMessage("call3", makeTextContent(originalText), false)

	result := truncateToolResult(ctx, "tool", "call3", msg)

	// Original should be unchanged
	if msg.Items[0].ToolCallResult.Output.Content[0].Text != originalText {
		t.Error("original message was mutated")
	}

	// Result should be different object
	if result == msg {
		t.Error("expected new message, got same pointer")
	}
}

func TestTruncateToolResult_ExactlyAtLimit(t *testing.T) {
	ctx := context.Background()
	// Exactly at the limit should NOT be truncated
	exactText := strings.Repeat("x", maxToolResultSize)
	msg := makeToolResultMessage("call4", makeTextContent(exactText), false)

	result := truncateToolResult(ctx, "tool", "call4", msg)
	if result != msg {
		t.Error("content exactly at limit should not be truncated")
	}
}

func TestTruncateToolResult_SkipTruncationMeta(t *testing.T) {
	ctx := context.Background()
	// Content with skip-truncation meta — entire result should be skipped.
	bigData := strings.Repeat("x", maxToolResultSize+5000)
	content := []mcp.Content{
		{
			Type: "image",
			Data: bigData,
			Meta: map[string]any{types.SkipTruncationMetaKey: true},
		},
	}
	msg := makeToolResultMessage("call-skip", content, false)

	result := truncateToolResult(ctx, "tool", "call-skip", msg)
	if result != msg {
		t.Error("expected same message returned when content has skip-truncation meta")
	}
}

func TestTruncateToolResult_SkipTruncationMeta_MixedContent(t *testing.T) {
	ctx := context.Background()

	// If any content item has skip-truncation meta, the entire result is skipped.
	bigText := strings.Repeat("t", maxToolResultSize+1000)
	content := []mcp.Content{
		{Type: "text", Text: bigText},
		{
			Type: "image",
			Data: "base64imagedata",
			Meta: map[string]any{types.SkipTruncationMetaKey: true},
		},
	}
	msg := makeToolResultMessage("call-mix", content, false)

	result := truncateToolResult(ctx, "tool", "call-mix", msg)
	if result != msg {
		t.Error("expected same message returned when any content has skip-truncation meta")
	}
}

func TestHasSkipTruncation(t *testing.T) {
	tests := []struct {
		name    string
		content []mcp.Content
		want    bool
	}{
		{"nil content", nil, false},
		{"no meta", []mcp.Content{{Type: "text"}}, false},
		{"empty meta", []mcp.Content{{Type: "text", Meta: map[string]any{}}}, false},
		{"false value", []mcp.Content{{Meta: map[string]any{types.SkipTruncationMetaKey: false}}}, false},
		{"true value", []mcp.Content{{Meta: map[string]any{types.SkipTruncationMetaKey: true}}}, true},
		{"non-bool value", []mcp.Content{{Meta: map[string]any{types.SkipTruncationMetaKey: "true"}}}, false},
		{"mixed - one has meta", []mcp.Content{
			{Type: "text", Text: "hello"},
			{Type: "image", Data: "data", Meta: map[string]any{types.SkipTruncationMetaKey: true}},
		}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := hasSkipTruncation(tt.content); got != tt.want {
				t.Errorf("hasSkipTruncation() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestTruncateToolResult_SpecialCharsInNames(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	ctx := contextWithSessionID(t, "default")
	bigText := strings.Repeat("x", maxToolResultSize+100)
	msg := makeToolResultMessage("call/5!@#", makeTextContent(bigText), false)

	result := truncateToolResult(ctx, "tool/name:special", "call/5!@#", msg)
	if result == msg {
		t.Fatal("expected truncated message")
	}

	// File should exist with sanitized name in the session working directory
	filePath := filepath.Join("sessions", "default", "truncated-outputs", "tool_name_special-call_5___.txt")
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		t.Errorf("expected file at %s", filePath)
	}
}
