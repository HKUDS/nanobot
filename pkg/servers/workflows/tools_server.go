package workflows

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/nanobot-ai/nanobot/pkg/version"
)

type ToolsServer struct {
	tools mcp.ServerTools
}

func NewToolsServer() *ToolsServer {
	s := &ToolsServer{}

	s.tools = mcp.NewServerTools(
		mcp.NewServerTool("recordWorkflowRun", "Record that a workflow was executed in the current chat session", s.recordWorkflowRun),
		mcp.NewServerTool("deleteWorkflow", "Delete a workflow by its URI", s.deleteWorkflow),
	)

	return s
}

func (s *ToolsServer) OnMessage(ctx context.Context, msg mcp.Message) {
	switch msg.Method {
	case "initialize":
		mcp.Invoke(ctx, msg, s.initialize)
	case "notifications/initialized":
		// nothing to do
	case "notifications/cancelled":
		mcp.HandleCancelled(ctx, msg)
	case "tools/list":
		mcp.Invoke(ctx, msg, s.tools.List)
	case "tools/call":
		mcp.Invoke(ctx, msg, s.tools.Call)
	default:
		msg.SendError(ctx, mcp.ErrRPCMethodNotFound.WithMessage("%v", msg.Method))
	}
}

func (s *ToolsServer) initialize(ctx context.Context, _ mcp.Message, params mcp.InitializeRequest) (*mcp.InitializeResult, error) {
	return &mcp.InitializeResult{
		ProtocolVersion: params.ProtocolVersion,
		Capabilities: mcp.ServerCapabilities{
			Tools: &mcp.ToolsServerCapability{},
		},
		ServerInfo: mcp.ServerInfo{
			Name:    version.Name,
			Version: version.Get().String(),
		},
	}, nil
}

func (s *ToolsServer) recordWorkflowRun(ctx context.Context, data struct {
	URI string `json:"uri"`
}) (string, error) {
	if _, err := parseWorkflowURI(data.URI); err != nil {
		return "", fmt.Errorf("failed to parse workflow URI: %w", err)
	}

	workflowSession := mcp.SessionFromContext(ctx).Root()
	if workflowSession == nil {
		return "", mcp.ErrRPCInvalidRequest.WithMessage("session not found")
	}

	var manager session.Manager
	if !workflowSession.Get(session.ManagerSessionKey, &manager) {
		return "", mcp.ErrRPCInvalidRequest.WithMessage("session manager not found")
	}

	sessionID := workflowSession.ID()
	if err := manager.DB.AddWorkflowRun(ctx, sessionID, data.URI); err != nil {
		return "", fmt.Errorf("failed to add workflow run: %w", err)
	}

	return fmt.Sprintf("%s run recorded for session %s", data.URI, sessionID), nil
}

func (s *ToolsServer) deleteWorkflow(_ context.Context, data struct {
	URI string `json:"uri"`
}) (string, error) {
	workflowName, err := parseWorkflowURI(data.URI)
	if err != nil {
		return "", fmt.Errorf("failed to parse workflow URI: %w", err)
	}

	workflowPath := filepath.Join(workflowsDir, workflowName+".md")
	if err := os.Remove(workflowPath); err != nil && !os.IsNotExist(err) {
		return "", fmt.Errorf("failed to delete workflow: %w", err)
	}

	return fmt.Sprintf("%s deleted", data.URI), nil
}
