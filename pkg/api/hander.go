package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func Handler(sessionManager *session.Manager, callBackAddress string) http.Handler {
	callBackAddress = strings.ReplaceAll(callBackAddress, "127.0.0.1", "localhost")
	callBackAddress = strings.ReplaceAll(callBackAddress, "0.0.0.0", "localhost")

	s := &server{
		server: mcp.Server{
			BaseURL: fmt.Sprintf("http://%s/mcp/ui", callBackAddress),
		},
		sessionManager: sessionManager,
	}
	mux := http.NewServeMux()

	routes(s, mux)

	return mux
}

func Cors(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", r.Header.Get("Access-Control-Request-Headers"))
		w.Header().Set("Access-Control-Expose-Headers", "Mcp-Session-Id")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		h.ServeHTTP(w, r)
	})
}

type server struct {
	server         mcp.Server
	sessionManager *session.Manager
}

func (s *server) setupContext(_ http.ResponseWriter, req *http.Request) (Context, error) {
	var (
		threadID   = req.PathValue("thread_id")
		chatClient *mcp.Client
		err        error
	)

	currentServer := s.server
	currentServer.Headers = map[string]string{
		"User-Agent":    req.Header.Get("User-Agent"),
		"Authorization": req.Header.Get("Authorization"),
		"Cookie":        req.Header.Get("Cookie"),
	}

	if threadID != "" {
		chatClient, err = mcp.NewClient(req.Context(), "nanobot.ui", currentServer, mcp.ClientOption{
			SessionState: &mcp.SessionState{
				ID: threadID,
				InitializeResult: mcp.InitializeResult{
					Capabilities: mcp.ServerCapabilities{
						Prompts: &mcp.PromptsServerCapability{
							ListChanged: true,
						},
						Resources: &mcp.ResourcesServerCapability{
							Subscribe:   true,
							ListChanged: true,
						},
						Tools: &mcp.ToolsServerCapability{},
					},
				},
				InitializeRequest: mcp.InitializeRequest{
					Capabilities: mcp.ClientCapabilities{
						Elicitation: &struct{}{},
					},
				},
				Attributes: nil,
			},
		})
		if err != nil {
			return Context{}, err
		}
	}

	return Context{
		ChatClient:     chatClient,
		SessionManager: s.sessionManager,
		MCPServer:      currentServer,
	}, nil
}

func (s *server) withContext(f func(rw http.ResponseWriter, req *http.Request) error) http.Handler {
	return s.api(func(rw http.ResponseWriter, req *http.Request) error {
		ctx, err := s.setupContext(rw, req)
		if err != nil {
			return err
		}
		defer ctx.Close()

		return f(rw, req.WithContext(context.WithValue(req.Context(), contextKey{}, ctx)))
	})
}

func (s *server) api(f func(rw http.ResponseWriter, req *http.Request) error) http.Handler {
	return http.HandlerFunc(func(rw http.ResponseWriter, req *http.Request) {
		if err := f(rw, req); err != nil {
			http.Error(rw, err.Error(), http.StatusInternalServerError)
		}
	})
}

type Context struct {
	ChatClient     *mcp.Client
	SessionManager *session.Manager
	MCPServer      mcp.Server
	ctx            context.Context
}

func (c Context) Close() {
	if c.ChatClient != nil {
		c.ChatClient.Close(false)
	}
}

func (c Context) Context() context.Context {
	return c.ctx
}

type contextKey struct{}

func getContext(ctx context.Context) Context {
	c, _ := ctx.Value(contextKey{}).(Context)
	c.ctx = ctx
	return c
}

type Server struct {
	client *mcp.Client
	cfg    types.Config
}

func Version(rw http.ResponseWriter, _ *http.Request) error {
	return json.NewEncoder(rw).Encode(
		map[string]any{},
	)
}
