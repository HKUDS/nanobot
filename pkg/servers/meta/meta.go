package meta

import (
	"context"
	"sync"

	"github.com/nanobot-ai/nanobot/pkg/fswatch"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/sessiondata"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/version"
	"log/slog"
)

type Server struct {
	tools           mcp.ServerTools
	data            *sessiondata.Data
	subscriptions   *fswatch.SubscriptionManager
	workflowWatcher *fswatch.Watcher
	sessionsWatcher *fswatch.Watcher
	watcherOnce     sync.Once
	watcherInitErr  error
}

func NewServer(data *sessiondata.Data) *Server {
	s := &Server{
		data:          data,
		subscriptions: fswatch.NewSubscriptionManager(context.Background()),
	}

	s.tools = mcp.NewServerTools(
		mcp.NewServerTool("list_chats", "Returns all previous chat threads", s.listChats),
		mcp.NewServerTool("update_chat", "Update fields of a give chat thread", s.updateChat),
		mcp.NewServerTool("list_agents", "List available agents and their meta data", s.listAgents),
	)

	return s
}

// Close stops file watchers and cleans up resources
func (s *Server) Close() error {
	var errs []error
	if s.workflowWatcher != nil {
		if err := s.workflowWatcher.Close(); err != nil {
			errs = append(errs, err)
		}
	}
	if s.sessionsWatcher != nil {
		if err := s.sessionsWatcher.Close(); err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) > 0 {
		return errs[0]
	}
	return nil
}

func (s *Server) OnMessage(ctx context.Context, msg mcp.Message) {
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
	case "resources/list":
		mcp.Invoke(ctx, msg, s.resourcesList)
	case "resources/read":
		mcp.Invoke(ctx, msg, s.resourcesRead)
	case "resources/subscribe":
		mcp.Invoke(ctx, msg, s.resourcesSubscribe)
	case "resources/unsubscribe":
		mcp.Invoke(ctx, msg, s.resourcesUnsubscribe)
	default:
		msg.SendError(ctx, mcp.ErrRPCMethodNotFound.WithMessage("%v", msg.Method))
	}
}

func (s *Server) initialize(ctx context.Context, msg mcp.Message, params mcp.InitializeRequest) (*mcp.InitializeResult, error) {
	if !types.IsUISession(ctx) {
		s.tools = mcp.NewServerTools()
		return &mcp.InitializeResult{
			ProtocolVersion: params.ProtocolVersion,
			ServerInfo: mcp.ServerInfo{
				Name:    version.Name,
				Version: version.Get().String(),
			},
		}, nil
	}

	// Track this session for sending list_changed notifications
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	s.subscriptions.AddSession(sessionID, msg.Session.Root())

	// Start watchers lazily
	if err := s.ensureWatchers(); err != nil {
		slog.Error("failed to start meta watchers", "error", err)
	}

	return &mcp.InitializeResult{
		ProtocolVersion: params.ProtocolVersion,
		Capabilities: mcp.ServerCapabilities{
			Tools: &mcp.ToolsServerCapability{},
			Resources: &mcp.ResourcesServerCapability{
				Subscribe:   true,
				ListChanged: true,
			},
		},
		ServerInfo: mcp.ServerInfo{
			Name:    version.Name,
			Version: version.Get().String(),
		},
	}, nil
}
