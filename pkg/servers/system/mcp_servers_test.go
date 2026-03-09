package system

import (
	"context"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func TestAddMCPServer_ValidatesURL(t *testing.T) {
	s := NewServer("")

	tests := []struct {
		name    string
		url     string
		wantErr string
	}{
		{
			name:    "empty URL",
			url:     "",
			wantErr: "url is required",
		},
		{
			name:    "invalid scheme",
			url:     "ftp://example.com/mcp",
			wantErr: "URL must use http or https scheme",
		},
		{
			name:    "no scheme",
			url:     "example.com/mcp",
			wantErr: "URL must use http or https scheme",
		},
		{
			name: "valid https URL",
			url:  "https://obot.example.com/mcp",
		},
		{
			name: "valid http URL",
			url:  "http://obot.example.com/mcp",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctx := context.Background()
			session := mcp.NewEmptySession(ctx)
			session.Set(mcp.SessionEnvMapKey, map[string]string{
				"MCP_SERVER_SEARCH_URL": "https://obot.example.com/search",
			})
			ctx = mcp.WithSession(ctx, session)

			_, err := s.addMCPServer(ctx, AddMCPServerParams{
				URL:  tt.url,
				Name: "test-server",
			})

			if tt.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil", tt.wantErr)
				}
				if got := err.Error(); !strings.Contains(got, tt.wantErr) {
					t.Errorf("error = %q, want to contain %q", got, tt.wantErr)
				}
			} else {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
			}
		})
	}
}

func TestAddMCPServer_ValidatesHostMatch(t *testing.T) {
	s := NewServer("")

	tests := []struct {
		name      string
		serverURL string
		searchURL string
		wantErr   bool
	}{
		{
			name:      "matching host",
			serverURL: "https://obot.example.com/mcp/server1",
			searchURL: "https://obot.example.com/search",
			wantErr:   false,
		},
		{
			name:      "mismatching host",
			serverURL: "https://evil.example.com/mcp",
			searchURL: "https://obot.example.com/search",
			wantErr:   true,
		},
		{
			name:      "matching host with port",
			serverURL: "https://obot.example.com:8443/mcp",
			searchURL: "https://obot.example.com:8443/search",
			wantErr:   false,
		},
		{
			name:      "mismatching port",
			serverURL: "https://obot.example.com:9999/mcp",
			searchURL: "https://obot.example.com:8443/search",
			wantErr:   true,
		},
		{
			name:      "no search URL configured",
			serverURL: "https://anything.example.com/mcp",
			searchURL: "",
			wantErr:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctx := context.Background()
			session := mcp.NewEmptySession(ctx)
			envMap := map[string]string{}
			if tt.searchURL != "" {
				envMap["MCP_SERVER_SEARCH_URL"] = tt.searchURL
			}
			session.Set(mcp.SessionEnvMapKey, envMap)
			ctx = mcp.WithSession(ctx, session)

			_, err := s.addMCPServer(ctx, AddMCPServerParams{
				URL:  tt.serverURL,
				Name: "test-server",
			})

			if tt.wantErr && err == nil {
				t.Fatal("expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestAddMCPServer_ValidatesName(t *testing.T) {
	s := NewServer("")

	tests := []struct {
		name    string
		srvName string
		wantErr string
	}{
		{
			name:    "empty name",
			srvName: "",
			wantErr: "name is required",
		},
		{
			name:    "name with slash",
			srvName: "my/server",
			wantErr: "must not contain '/'",
		},
		{
			name:    "reserved name nanobot.system",
			srvName: "nanobot.system",
			wantErr: "reserved",
		},
		{
			name:    "valid name",
			srvName: "my-custom-server",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctx := context.Background()
			session := mcp.NewEmptySession(ctx)
			session.Set(mcp.SessionEnvMapKey, map[string]string{
				"MCP_SERVER_SEARCH_URL": "https://obot.example.com/search",
			})
			ctx = mcp.WithSession(ctx, session)

			_, err := s.addMCPServer(ctx, AddMCPServerParams{
				URL:  "https://obot.example.com/mcp",
				Name: tt.srvName,
			})

			if tt.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil", tt.wantErr)
				}
				if got := err.Error(); !strings.Contains(got, tt.wantErr) {
					t.Errorf("error = %q, want to contain %q", got, tt.wantErr)
				}
			} else {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
			}
		})
	}
}

func TestRemoveMCPServer_NonExistentIsNotError(t *testing.T) {
	s := NewServer("")

	ctx := context.Background()
	session := mcp.NewEmptySession(ctx)
	ctx = mcp.WithSession(ctx, session)

	// Should not error even when no dynamic servers exist
	result, err := s.removeMCPServer(ctx, RemoveMCPServerParams{
		Name: "nonexistent",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["success"] != true {
		t.Error("expected success to be true")
	}
}

func TestConfigHook_DynamicServerCollision(t *testing.T) {
	s := NewServer("")

	ctx := context.Background()
	session := mcp.NewEmptySession(ctx)
	session.Set(mcp.SessionEnvMapKey, map[string]string{
		"MCP_SERVER_SEARCH_URL": "https://obot.example.com/search",
	})

	// Set up dynamic servers that include a name collision with mcp-server-search
	dynamicServers := DynamicMCPServers{
		"mcp-server-search": {URL: "https://evil.example.com/malicious"},
		"legitimate-server": {URL: "https://obot.example.com/legit"},
	}
	session.Set(DynamicMCPServersSessionKey, dynamicServers)
	ctx = mcp.WithSession(ctx, session)

	params := types.AgentConfigHook{
		Agent: &types.HookAgent{
			Name: "test-agent",
		},
	}

	result, err := s.config(ctx, params)
	if err != nil {
		t.Fatalf("config() error = %v", err)
	}

	// mcp-server-search should NOT be overwritten by dynamic server
	mcpSearch, exists := result.MCPServers["mcp-server-search"]
	if !exists {
		t.Fatal("expected mcp-server-search to exist")
	}
	if mcpSearch.URL != "https://obot.example.com/search" {
		t.Errorf("mcp-server-search URL = %q, want original URL, not dynamic override", mcpSearch.URL)
	}

	// legitimate-server should be added
	legit, exists := result.MCPServers["legitimate-server"]
	if !exists {
		t.Fatal("expected legitimate-server to exist")
	}
	if legit.URL != "https://obot.example.com/legit" {
		t.Errorf("legitimate-server URL = %q, want %q", legit.URL, "https://obot.example.com/legit")
	}
}

func TestConfigHook_DynamicServersMerged(t *testing.T) {
	s := NewServer("")

	ctx := context.Background()
	session := mcp.NewEmptySession(ctx)
	session.Set(mcp.SessionEnvMapKey, map[string]string{})

	dynamicServers := DynamicMCPServers{
		"server-a": {URL: "https://example.com/a"},
		"server-b": {URL: "https://example.com/b"},
	}
	session.Set(DynamicMCPServersSessionKey, dynamicServers)
	ctx = mcp.WithSession(ctx, session)

	params := types.AgentConfigHook{
		Agent: &types.HookAgent{
			Name: "test-agent",
		},
	}

	result, err := s.config(ctx, params)
	if err != nil {
		t.Fatalf("config() error = %v", err)
	}

	// Both servers should be in MCPServers
	for _, name := range []string{"server-a", "server-b"} {
		if _, exists := result.MCPServers[name]; !exists {
			t.Errorf("expected %q to be in MCPServers", name)
		}
	}

	// Both should be in agent's MCPServers list
	agentServers := result.Agent.MCPServers
	for _, name := range []string{"server-a", "server-b"} {
		found := false
		for _, s := range agentServers {
			if s == name {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("expected %q to be in agent MCPServers list", name)
		}
	}
}
