package workflows

import (
	"context"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/session"
)

func TestRecordWorkflowRun_DeduplicatesURI(t *testing.T) {
	s := NewToolsServer()
	ctx := t.Context()
	manager, err := session.NewManager("sqlite::memory:")
	if err != nil {
		t.Fatalf("failed to create session manager: %v", err)
	}

	if err := manager.DB.Create(ctx, &session.Session{
		SessionID: "test-session",
		AccountID: "test-account",
		Type:      "thread",
	}); err != nil {
		t.Fatalf("failed to create test session record: %v", err)
	}

	serverSession, err := mcp.NewExistingServerSession(ctx, mcp.SessionState{ID: "test-session"}, mcp.MessageHandlerFunc(func(context.Context, mcp.Message) {}))
	if err != nil {
		t.Fatalf("failed to create test server session: %v", err)
	}
	defer serverSession.Close(false)

	serverSession.GetSession().Set(session.ManagerSessionKey, manager)
	ctx = mcp.WithSession(ctx, serverSession.GetSession())

	data := struct {
		URI string `json:"uri"`
	}{
		URI: "workflow:///test-workflow",
	}
	if _, err := s.recordWorkflowRun(ctx, data); err != nil {
		t.Fatalf("first recordWorkflowRun() failed: %v", err)
	}

	if _, err := s.recordWorkflowRun(ctx, data); err != nil {
		t.Fatalf("second recordWorkflowRun() failed: %v", err)
	}

	workflowURIs, err := manager.DB.ListWorkflowURIs(ctx, "test-session")
	if err != nil {
		t.Fatalf("failed to load stored workflow URIs: %v", err)
	}

	expected := map[string][]string{
		"test-session": {data.URI},
	}
	if !maps.EqualFunc(workflowURIs, expected, slices.Equal) {
		t.Fatalf("workflowURIs = %#v, want %#v", workflowURIs, expected)
	}
}

func TestDeleteWorkflow_RemovesFile(t *testing.T) {
	tempDir := t.TempDir()
	restore := withWorkingDir(t, tempDir)
	defer restore()

	workflowsPath := filepath.Join(tempDir, workflowsDir)
	if err := os.MkdirAll(workflowsPath, 0755); err != nil {
		t.Fatalf("failed to create workflows directory: %v", err)
	}

	workflowPath := filepath.Join(workflowsPath, "to-delete.md")
	if err := os.WriteFile(workflowPath, []byte("# test"), 0644); err != nil {
		t.Fatalf("failed to write workflow file: %v", err)
	}

	s := NewToolsServer()
	if _, err := s.deleteWorkflow(t.Context(), struct {
		URI string `json:"uri"`
	}{URI: "workflow:///to-delete"}); err != nil {
		t.Fatalf("deleteWorkflow() failed: %v", err)
	}

	if _, err := os.Stat(workflowPath); !os.IsNotExist(err) {
		t.Fatalf("expected workflow file to be deleted, stat err: %v", err)
	}
}
