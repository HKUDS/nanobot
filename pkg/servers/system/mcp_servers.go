package system

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"log/slog"
)

var (
	// reservedServerNames contains names that cannot be used for dynamic MCP servers
	reservedServerNames = map[string]struct{}{
		"mcp-server-search": {},
	}

	// reservedServerNamePrefixes contains prefixes that cannot be used for dynamic MCP servers
	reservedServerNamePrefixes = []string{"nanobot."}
)

// DynamicMCPServersSessionKey is the session key for storing dynamically added MCP servers
const DynamicMCPServersSessionKey = "dynamicMCPServers"

// DynamicMCPServers stores dynamically added MCP servers for a session
type DynamicMCPServers map[string]types.AgentConfigHookMCPServer

// Serialize implements mcp.Serializable
func (d DynamicMCPServers) Serialize() (any, error) {
	return d, nil
}

// Deserialize implements mcp.Deserializable
func (d *DynamicMCPServers) Deserialize(data any) (any, error) {
	result := make(DynamicMCPServers)
	if err := mcp.JSONCoerce(data, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// AddMCPServerParams are the parameters for the addMCPServer tool
type AddMCPServerParams struct {
	URL  string `json:"url"`
	Name string `json:"name"`
}

// RemoveMCPServerParams are the parameters for the removeMCPServer tool
type RemoveMCPServerParams struct {
	Name string `json:"name"`
}

func (s *Server) addMCPServer(ctx context.Context, params AddMCPServerParams) (map[string]any, error) {
	if params.URL == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("url is required")
	}
	if params.Name == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("name is required")
	}

	// Validate server name
	if strings.Contains(params.Name, "/") {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("server name must not contain '/'")
	}
	if _, exists := reservedServerNames[params.Name]; exists {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("server name '%s' is reserved", params.Name)
	}
	for _, prefix := range reservedServerNamePrefixes {
		if strings.HasPrefix(params.Name, prefix) {
			return nil, mcp.ErrRPCInvalidParams.WithMessage("server name '%s' is reserved", params.Name)
		}
	}

	// Validate URL format
	parsedURL, err := url.Parse(params.URL)
	if err != nil {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("invalid URL: %v", err)
	}
	if parsedURL.Scheme != "http" && parsedURL.Scheme != "https" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("URL must use http or https scheme")
	}
	if parsedURL.Host == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("URL must include a non-empty host")
	}

	// Get session
	session := mcp.SessionFromContext(ctx)
	if session == nil {
		return nil, mcp.ErrRPCInternal.WithMessage("no session found")
	}

	// Validate that the URL hostname+port matches the MCP_SERVER_SEARCH_URL host (Obot host)
	envMap := session.GetEnvMap()
	searchURL, ok := envMap["MCP_SERVER_SEARCH_URL"]
	if !ok || strings.TrimSpace(searchURL) == "" {
		return nil, mcp.ErrRPCInternal.WithMessage("MCP_SERVER_SEARCH_URL is not configured")
	}

	searchParsed, err := url.Parse(searchURL)
	if err != nil || searchParsed.Host == "" {
		return nil, mcp.ErrRPCInternal.WithMessage("MCP_SERVER_SEARCH_URL is invalid: %v", err)
	}

	if parsedURL.Host != searchParsed.Host {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("URL host %q does not match the allowed host %q", parsedURL.Host, searchParsed.Host)
	}
	// Use MCP_API_KEY from the environment as the Bearer token for dynamic servers
	var headers map[string]string

	if apiKey := envMap["MCP_API_KEY"]; apiKey != "" {
		headers = map[string]string{
			"Authorization": "Bearer " + apiKey,
		}
	} else {
		slog.Info("MCP_API_KEY environment variable is not set, auth will fallback to OAuth")
	}

	// Create the new server config
	newServer := types.AgentConfigHookMCPServer{
		URL:     params.URL,
		Headers: headers,
	}

	// Get or create dynamic servers map from session
	var dynamicServers DynamicMCPServers
	if !session.Get(DynamicMCPServersSessionKey, &dynamicServers) {
		dynamicServers = make(DynamicMCPServers)
	}

	// Add new server to map
	dynamicServers[params.Name] = newServer

	// Save back to session
	session.Set(DynamicMCPServersSessionKey, dynamicServers)

	result := map[string]any{
		"success": true,
		"name":    params.Name,
		"url":     params.URL,
	}

	// Best-effort: try to list the server's tools so the LLM knows their real names
	tools, err := listServerTools(ctx, params.URL, headers)
	if err != nil {
		slog.Debug("failed to list tools for MCP server", "server", params.Name, "error", err)
		result["message"] = fmt.Sprintf("Successfully added MCP server '%s'. The server's tools will be available in the next agent turn.", params.Name)
	} else {
		toolList := make([]string, 0, len(tools))
		for _, t := range tools {
			toolList = append(toolList, t.Name)
		}
		result["tools"] = toolList
		result["message"] = fmt.Sprintf("Successfully added MCP server '%s' with %d tool(s). The tools will be available in the next agent turn.", params.Name, len(tools))
	}

	return result, nil
}

// listServerTools creates a temporary MCP client to fetch the tool list from a server.
func listServerTools(ctx context.Context, serverURL string, headers map[string]string) ([]mcp.Tool, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	client, err := mcp.NewClient(ctx, "tmp-tool-list", mcp.Server{
		BaseURL: serverURL,
		Headers: headers,
	})
	if err != nil {
		return nil, fmt.Errorf("connecting to server: %w", err)
	}
	defer client.Close(true)

	result, err := client.ListTools(ctx)
	if err != nil {
		return nil, fmt.Errorf("listing tools: %w", err)
	}

	return result.Tools, nil
}

func (s *Server) removeMCPServer(ctx context.Context, params RemoveMCPServerParams) (map[string]any, error) {
	if params.Name == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("name is required")
	}

	// Get session
	session := mcp.SessionFromContext(ctx)
	if session == nil {
		return nil, mcp.ErrRPCInternal.WithMessage("no session found")
	}

	// Get dynamic servers map from session
	var dynamicServers DynamicMCPServers
	if session.Get(DynamicMCPServersSessionKey, &dynamicServers) {
		// Delete server from map (no-op if it doesn't exist)
		delete(dynamicServers, params.Name)

		// Save back to session
		session.Set(DynamicMCPServersSessionKey, dynamicServers)
	}

	return map[string]any{
		"success": true,
		"name":    params.Name,
		"message": fmt.Sprintf("Successfully removed MCP server '%s'. The server's tools will no longer be available in the next agent turn.", params.Name),
	}, nil
}
