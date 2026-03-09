package types

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/hexops/autogold/v2"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

func TestCompletionItem_Text(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		Content: &mcp.Content{
			Type: "text",
			Text: "Hello, world!",
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"hasMore":false,"id":"test-id","partial":false,"type":"text","text":"Hello, world!"}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	// Compare relevant fields individually since unmarshal may populate zero values
	if item.Content.Type != unmarshalledItem.Content.Type {
		t.Errorf("Expected content type %q but got %q", item.Content.Type, unmarshalledItem.Content.Type)
	}
	if item.Content.Text != unmarshalledItem.Content.Text {
		t.Errorf("Expected content text %q but got %q", item.Content.Text, unmarshalledItem.Content.Text)
	}
	if item.ID != unmarshalledItem.ID || item.Partial != unmarshalledItem.Partial || item.HasMore != unmarshalledItem.HasMore {
		t.Errorf("Expected unmarshalled item fields to match original, but got: %+v", unmarshalledItem)
	}
}

func TestCompletionItem_Image(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		Content: &mcp.Content{
			Type: "image",
			Data: "base64-image-data",
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"hasMore":false,"id":"test-id","partial":false,"type":"image","data":"base64-image-data"}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	// Compare relevant fields individually since unmarshal may populate zero values
	if item.Content.Type != unmarshalledItem.Content.Type {
		t.Errorf("Expected content type %q but got %q", item.Content.Type, unmarshalledItem.Content.Type)
	}
	if item.Content.Data != unmarshalledItem.Content.Data {
		t.Errorf("Expected content data %q but got %q", item.Content.Data, unmarshalledItem.Content.Data)
	}
	if item.ID != unmarshalledItem.ID || item.Partial != unmarshalledItem.Partial || item.HasMore != unmarshalledItem.HasMore {
		t.Errorf("Expected unmarshalled item fields to match original, but got: %+v", unmarshalledItem)
	}
}

func TestCompletionItem_ResourceLink(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		Content: &mcp.Content{
			Type:     "resource_link",
			URI:      "file:///docs/example.pdf",
			Name:     "example.pdf",
			MIMEType: "application/pdf",
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	if unmarshalledItem.Content == nil {
		t.Fatalf("expected content to be present after unmarshal, got nil")
	}
	if unmarshalledItem.Content.Type != "resource_link" {
		t.Fatalf("expected content type resource_link, got %q", unmarshalledItem.Content.Type)
	}
	if unmarshalledItem.Content.URI != "file:///docs/example.pdf" {
		t.Fatalf("expected URI to round-trip, got %q", unmarshalledItem.Content.URI)
	}
	if unmarshalledItem.Content.Name != "example.pdf" {
		t.Fatalf("expected Name to round-trip, got %q", unmarshalledItem.Content.Name)
	}
	if unmarshalledItem.Content.MIMEType != "application/pdf" {
		t.Fatalf("expected MIMEType to round-trip, got %q", unmarshalledItem.Content.MIMEType)
	}
}

func TestCompletionItem_Tool(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		ToolCall: &ToolCall{
			Arguments:  "test-arguments",
			CallID:     "test-call-id",
			Name:       "test-name",
			Target:     "test-target",
			TargetType: "test-target-type",
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"id":"test-id","type":"tool","arguments":"test-arguments","callID":"test-call-id","name":"test-name","target":"test-target","targetType":"test-target-type"}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	if !reflect.DeepEqual(item, unmarshalledItem) {
		t.Errorf("Expected unmarshalled item to be equal to original item, but got: %+v", unmarshalledItem)
	}
}

func TestCompletionItem_ToolResult(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		ToolCallResult: &ToolCallResult{
			CallID: "test-call-id",
			Output: CallResult{
				Content: []mcp.Content{
					{
						Type: "text",
						Text: "This is a tool result",
					},
				},
			},
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"id":"test-id","type":"tool","output":{"content":[{"type":"text","text":"This is a tool result"}]},"callID":"test-call-id"}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	if !reflect.DeepEqual(item, unmarshalledItem) {
		t.Errorf("Expected unmarshalled item to be equal to original item, but got: %+v", unmarshalledItem)
	}
}

func TestCompletionItem_ToolBoth(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		ToolCall: &ToolCall{
			Arguments:  "test-arguments",
			CallID:     "test-call-id",
			Name:       "test-name",
			Target:     "test-target",
			TargetType: "test-target-type",
		},
		ToolCallResult: &ToolCallResult{
			CallID: "test-call-id",
			Output: CallResult{
				Content: []mcp.Content{
					{
						Type: "text",
						Text: "This is a tool result",
					},
				},
			},
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"id":"test-id","type":"tool","output":{"content":[{"type":"text","text":"This is a tool result"}]},"arguments":"test-arguments","callID":"test-call-id","name":"test-name","target":"test-target","targetType":"test-target-type"}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	if !reflect.DeepEqual(item, unmarshalledItem) {
		t.Errorf("Expected unmarshalled item to be equal to original item, but got: %+v", unmarshalledItem)
	}
}

func TestCompletionItem_Reasoning(t *testing.T) {
	item := CompletionItem{
		ID: "test-id",
		Reasoning: &Reasoning{
			EncryptedContent: "encrypted-content",
			Summary: []SummaryText{
				{Text: "This is a summary of the reasoning."},
			},
		},
	}

	data, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("Failed to marshal CompletionItem: %v", err)
	}

	autogold.Expect(`{"id":"test-id","type":"reasoning","encryptedContent":"encrypted-content","summary":[{"text":"This is a summary of the reasoning."}]}`).Equal(t, string(data))

	var unmarshalledItem CompletionItem
	if err := json.Unmarshal(data, &unmarshalledItem); err != nil {
		t.Fatalf("Failed to unmarshal CompletionItem: %v", err)
	}

	if !reflect.DeepEqual(item, unmarshalledItem) {
		t.Errorf("Expected unmarshalled item to be equal to original item, but got: %+v", unmarshalledItem)
	}
}
