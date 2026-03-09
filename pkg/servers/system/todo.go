package system

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type TodoItem struct {
	Content    string `json:"content"`
	Status     string `json:"status"`
	ActiveForm string `json:"activeForm"`
}

// TodoWrite tool
type TodoWriteParams struct {
	Todos []TodoItem `json:"todos"`
}

// listTodoResources returns the todo list resource.
func (s *Server) listTodoResources() []mcp.Resource {
	return []mcp.Resource{
		{
			URI:         "todo:///list",
			Name:        "Todo List",
			Description: "The current todo list for tracking tasks",
			MimeType:    "application/json",
		},
	}
}

// readTodoResource reads the todo list resource.
func (s *Server) readTodoResource(ctx context.Context, uri string) (*mcp.ReadResourceResult, error) {
	if uri != "todo:///list" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("invalid todo URI, expected todo:///list")
	}

	// Get session ID
	sessionID, _ := types.GetSessionAndAccountID(ctx)

	// Read from .nanobot/<sessionId>/status/todo.json
	todoPath := filepath.Join(".nanobot", sessionID, "status", "todo.json")

	// Check if file exists
	var contentStr string
	if _, err := os.Stat(todoPath); os.IsNotExist(err) {
		// Return empty list if file doesn't exist
		contentStr = "[]"
	} else {
		// Read file
		data, err := os.ReadFile(todoPath)
		if err != nil {
			return nil, fmt.Errorf("failed to read todo file: %w", err)
		}
		contentStr = string(data)
	}

	return &mcp.ReadResourceResult{
		Contents: []mcp.ResourceContent{
			{
				URI:      uri,
				Name:     "Todo List",
				MIMEType: "application/json",
				Text:     &contentStr,
			},
		},
	}, nil
}

// subscribeTodoResource subscribes to the todo list resource.
func (s *Server) subscribeTodoResource(uri string) error {
	if uri != "todo:///list" {
		return mcp.ErrRPCInvalidParams.WithMessage("invalid todo URI, expected todo:///list")
	}
	// Subscription is handled by the shared subscription manager
	return nil
}

func (s *Server) todoWrite(ctx context.Context, params TodoWriteParams) (string, error) {
	// Validate only one in_progress task
	var inProgressCount int
	for _, todo := range params.Todos {
		if todo.Status == "in_progress" {
			inProgressCount++
		}
	}

	if inProgressCount > 1 {
		return "", mcp.ErrRPCInvalidParams.WithMessage("only one task can be in_progress at a time")
	}

	// Get session ID
	sessionID, _ := types.GetSessionAndAccountID(ctx)

	// Write to .nanobot/<sessionId>/status/todo.json
	todoPath := filepath.Join(".nanobot", sessionID, "status", "todo.json")

	// Create directories
	if err := os.MkdirAll(filepath.Dir(todoPath), 0755); err != nil {
		return "", fmt.Errorf("failed to create todo directory: %w", err)
	}

	// Marshal JSON
	todoJSON, err := json.MarshalIndent(params.Todos, "", "  ")
	if err != nil {
		return "", fmt.Errorf("failed to marshal todos: %w", err)
	}

	// Write file
	if err := os.WriteFile(todoPath, todoJSON, 0644); err != nil {
		return "", fmt.Errorf("failed to write todo file: %w", err)
	}

	// Send resource updated notification to subscribed sessions
	s.subscriptions.SendResourceUpdatedNotification("todo:///list")

	return fmt.Sprintf("Todo list updated:\n\n%s", string(todoJSON)), nil
}
