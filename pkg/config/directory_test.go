package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/types"
)

func TestLoadFromDirectory_Simple(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-simple")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check agent loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["main"]
	if !exists {
		t.Fatal("expected 'main' agent to exist")
	}

	if agent.Name != "Main Assistant" {
		t.Errorf("expected agent name 'Main Assistant', got '%s'", agent.Name)
	}

	if agent.Model != "gpt-4" {
		t.Errorf("expected model 'gpt-4', got '%s'", agent.Model)
	}

	if agent.Instructions.Instructions == "" {
		t.Error("expected non-empty instructions")
	}

	if !strings.Contains(agent.Instructions.Instructions, "helpful assistant") {
		t.Errorf("expected instructions to contain 'helpful assistant', got: %s", agent.Instructions.Instructions)
	}

	// Check MCP server loaded
	if len(config.MCPServers) != 1 {
		t.Errorf("expected 1 MCP server, got %d", len(config.MCPServers))
	}

	server, exists := config.MCPServers["myserver"]
	if !exists {
		t.Fatal("expected 'myserver' MCP server to exist")
	}

	if server.BaseURL != "https://example.com/mcp" {
		t.Errorf("expected MCP server URL 'https://example.com/mcp', got '%s'", server.BaseURL)
	}

	// Check entrypoint set to main
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "main" {
		t.Errorf("expected entrypoint ['main'], got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_MultipleAgents(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-multiple")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check both agents loaded
	if len(config.Agents) != 2 {
		t.Errorf("expected 2 agents, got %d", len(config.Agents))
	}

	mainAgent, exists := config.Agents["main"]
	if !exists {
		t.Fatal("expected 'main' agent to exist")
	}

	if mainAgent.Name != "Main Agent" {
		t.Errorf("expected main agent name 'Main Agent', got '%s'", mainAgent.Name)
	}

	helperAgent, exists := config.Agents["helper"]
	if !exists {
		t.Fatal("expected 'helper-agent' agent to exist (from id field)")
	}

	if helperAgent.Name != "Helper Agent" {
		t.Errorf("expected helper agent name 'Helper Agent', got '%s'", helperAgent.Name)
	}

	// Both agents have no mode specified (defaults to ""), so both should be in entrypoint
	if len(config.Publish.Entrypoint) != 2 {
		t.Errorf("expected 2 agents in entrypoint, got %d: %v", len(config.Publish.Entrypoint), config.Publish.Entrypoint)
	}

	// Check that both agents are in entrypoint
	entrypointMap := make(map[string]bool)
	for _, agentID := range config.Publish.Entrypoint {
		entrypointMap[agentID] = true
	}

	if !entrypointMap["helper"] {
		t.Error("expected 'helper' agent in entrypoint")
	}

	if !entrypointMap["main"] {
		t.Error("expected 'main' agent in entrypoint")
	}
}

func TestLoadFromDirectory_JSON(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-json")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check MCP server loaded from JSON
	server, exists := config.MCPServers["jsonserver"]
	if !exists {
		t.Fatal("expected 'jsonserver' MCP server to exist")
	}

	if server.BaseURL != "https://example.com/json" {
		t.Errorf("expected MCP server URL 'https://example.com/json', got '%s'", server.BaseURL)
	}
}

func TestLoadFromDirectory_BothMCPFiles_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-both-mcp")
	if err == nil {
		t.Fatal("expected error when both mcp-servers.yaml and mcp-servers.json exist")
	}

	if !strings.Contains(err.Error(), "both mcp-servers.yaml and mcp-servers.json found") {
		t.Errorf("expected error about both files, got: %v", err)
	}
}

func TestLoadFromDirectory_NoMCPServers(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-no-mcp")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	if len(config.MCPServers) != 0 {
		t.Errorf("expected 0 MCP servers, got %d", len(config.MCPServers))
	}
}

func TestLoadFromDirectory_WithREADME(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-with-readme")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Should only have 1 agent (main.md), README.md should be ignored
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent (README.md should be ignored), got %d", len(config.Agents))
	}

	_, hasMain := config.Agents["main"]
	if !hasMain {
		t.Error("expected 'main' agent to exist")
	}

	_, hasREADME := config.Agents["README"]
	if hasREADME {
		t.Error("README.md should not be loaded as an agent")
	}
}

func TestLoadFromDirectory_HiddenFiles(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-hidden")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Should only have 1 agent (main.md), not .hidden.md
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent (hidden files should be ignored), got %d", len(config.Agents))
	}

	_, hasMain := config.Agents["main"]
	if !hasMain {
		t.Error("expected 'main' agent to exist")
	}

	_, hasHidden := config.Agents[".hidden"]
	if hasHidden {
		t.Error("hidden agent should not be loaded")
	}
}

func TestLoadFromDirectory_InvalidYAML_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-invalid-yaml")
	if err == nil {
		t.Fatal("expected error for invalid YAML front-matter")
	}

	if !strings.Contains(err.Error(), "invalid YAML") && !strings.Contains(err.Error(), "unmarshal") {
		t.Errorf("expected error about invalid YAML, got: %v", err)
	}
}

func TestLoadFromDirectory_MissingServer_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-missing-server")
	if err == nil {
		t.Fatal("expected error when agent references non-existent MCP server")
	}

	if !strings.Contains(err.Error(), "references MCP server") || !strings.Contains(err.Error(), "nonexistent") {
		t.Errorf("expected error about missing MCP server, got: %v", err)
	}
}

func TestHasMarkdownFiles(t *testing.T) {
	// Directory with agents/ subdirectory containing .md files
	hasMd, err := hasMarkdownFiles("testdata/directory-simple")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !hasMd {
		t.Error("expected directory-simple to have .md files in agents/")
	}

	// Directory that doesn't exist - should return false without error
	// since it simply means no agents/ subdirectory exists
	hasMd, err = hasMarkdownFiles("testdata/nonexistent")
	if err != nil {
		t.Fatalf("unexpected error for non-existent directory: %v", err)
	}
	if hasMd {
		t.Error("expected non-existent directory to not have .md files")
	}
}

func TestParseMarkdownAgent_IDFromFilename(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-simple/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should use filename (main.md -> main)
	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	if agent.Name != "Main Assistant" {
		t.Errorf("expected name 'Main Assistant', got '%s'", agent.Name)
	}
}

func TestParseMarkdownAgent_AllFields(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-simple/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	// Check various fields from front-matter
	if agent.Model != "gpt-4" {
		t.Errorf("expected model 'gpt-4', got '%s'", agent.Model)
	}

	if len(agent.MCPServers) != 1 || agent.MCPServers[0] != "myserver" {
		t.Errorf("expected mcpServers ['myserver'], got %v", agent.MCPServers)
	}

	if len(agent.Tools) != 1 || agent.Tools[0] != "myserver" {
		t.Errorf("expected tools ['myserver'], got %v", agent.Tools)
	}

	if agent.Temperature == nil || agent.Temperature.String() != "0.7" {
		t.Errorf("expected temperature 0.7, got %v", agent.Temperature)
	}

	if agent.MaxTokens != 1000 {
		t.Errorf("expected maxTokens 1000, got %d", agent.MaxTokens)
	}

	// Check instructions from body
	if !strings.Contains(agent.Instructions.Instructions, "helpful assistant") {
		t.Errorf("expected instructions to contain 'helpful assistant', got: %s", agent.Instructions.Instructions)
	}
}

func TestLoadFromDirectory_DefaultAgent_Single(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-default-single")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check agent loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["agent"]
	if !exists {
		t.Fatal("expected 'agent' agent to exist")
	}

	if agent.Name != "Single Default Agent" {
		t.Errorf("expected agent name 'Single Default Agent', got '%s'", agent.Name)
	}

	// Check entrypoint set to the default agent
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "agent" {
		t.Errorf("expected entrypoint ['agent'], got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_DefaultAgent_Explicit(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-default-explicit")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check both agents loaded
	if len(config.Agents) != 2 {
		t.Errorf("expected 2 agents, got %d", len(config.Agents))
	}

	alphaAgent, exists := config.Agents["alpha"]
	if !exists {
		t.Fatal("expected 'alpha' agent to exist")
	}

	if alphaAgent.Name != "Alpha Agent" {
		t.Errorf("expected alpha agent name 'Alpha Agent', got '%s'", alphaAgent.Name)
	}

	zuluAgent, exists := config.Agents["zulu"]
	if !exists {
		t.Fatal("expected 'zulu' agent to exist")
	}

	if zuluAgent.Name != "Zulu Agent" {
		t.Errorf("expected zulu agent name 'Zulu Agent', got '%s'", zuluAgent.Name)
	}

	// Both agents have no mode specified (defaults to ""), so both should be in entrypoint
	// The explicitly marked default agent (zulu) should also be included (but already is)
	if len(config.Publish.Entrypoint) != 2 {
		t.Errorf("expected 2 agents in entrypoint, got %d: %v", len(config.Publish.Entrypoint), config.Publish.Entrypoint)
	}

	// Check that both agents are in entrypoint
	entrypointMap := make(map[string]bool)
	for _, agentID := range config.Publish.Entrypoint {
		entrypointMap[agentID] = true
	}

	if !entrypointMap["alpha"] {
		t.Error("expected 'alpha' agent in entrypoint")
	}

	if !entrypointMap["zulu"] {
		t.Error("expected 'zulu' agent (explicitly marked default) in entrypoint")
	}
}

func TestLoadFromDirectory_DefaultAgent_MultipleDefaults_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-default-multiple-error")
	if err == nil {
		t.Fatal("expected error when multiple agents are marked as default")
	}

	if !strings.Contains(err.Error(), "multiple agents marked as default") {
		t.Errorf("expected error about multiple default agents, got: %v", err)
	}

	// Error should mention both agent IDs
	if !strings.Contains(err.Error(), "first") || !strings.Contains(err.Error(), "second") {
		t.Errorf("expected error to mention both 'first' and 'second' agents, got: %v", err)
	}
}

func TestLoadFromDirectory_DefaultSubagent_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-default-subagent-error")
	if err == nil {
		t.Fatal("expected error when agent is both default and subagent")
	}

	if !strings.Contains(err.Error(), "cannot be both 'subagent' and 'default'") {
		t.Errorf("expected error about agent being both subagent and default, got: %v", err)
	}

	if !strings.Contains(err.Error(), "agent") {
		t.Errorf("expected error to mention agent name, got: %v", err)
	}
}

func TestParseMarkdownAgent_DefaultField(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-default-single/agents/agent.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "agent" {
		t.Errorf("expected agent ID 'agent', got '%s'", agentID)
	}

	if agent.Default != true {
		t.Errorf("expected Default field to be true, got %v", agent.Default)
	}

	if agent.Agent.Name != "Single Default Agent" {
		t.Errorf("expected name 'Single Default Agent', got '%s'", agent.Agent.Name)
	}
}

func TestParseMarkdownAgent_NoDefaultField(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-simple/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	// Default should be false when not specified
	if agent.Default != false {
		t.Errorf("expected Default field to be false when not specified, got %v", agent.Default)
	}
}

// Tests for mode field

func TestLoadFromDirectory_ModeChatAddsToEntrypoint(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-mode-chat")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Agent should be loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["agent"]
	if !exists {
		t.Fatal("expected 'agent' agent to exist")
	}

	if agent.Name != "Chat Mode Agent" {
		t.Errorf("expected agent name 'Chat Mode Agent', got '%s'", agent.Name)
	}

	// mode: chat should add agent to entrypoint
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "agent" {
		t.Errorf("expected entrypoint ['agent'] for mode: chat, got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_ModePrimaryAddsToEntrypoint(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-mode-primary")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Agent should be loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["agent"]
	if !exists {
		t.Fatal("expected 'agent' agent to exist")
	}

	if agent.Name != "Primary Mode Agent" {
		t.Errorf("expected agent name 'Primary Mode Agent', got '%s'", agent.Name)
	}

	// mode: primary should add agent to entrypoint
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "agent" {
		t.Errorf("expected entrypoint ['agent'] for mode: primary, got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_ModeAllAddsToEntrypoint(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-mode-all")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Agent should be loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["agent"]
	if !exists {
		t.Fatal("expected 'agent' agent to exist")
	}

	if agent.Name != "All Mode Agent" {
		t.Errorf("expected agent name 'All Mode Agent', got '%s'", agent.Name)
	}

	// mode: all should add agent to entrypoint
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "agent" {
		t.Errorf("expected entrypoint ['agent'] for mode: all, got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_ModeSubagentNotInEntrypoint(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-mode-subagent")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Both agents should be loaded
	if len(config.Agents) != 2 {
		t.Errorf("expected 2 agents, got %d", len(config.Agents))
	}

	primaryAgent, exists := config.Agents["primary"]
	if !exists {
		t.Fatal("expected 'primary' agent to exist")
	}

	if primaryAgent.Name != "Primary Agent" {
		t.Errorf("expected primary agent name 'Primary Agent', got '%s'", primaryAgent.Name)
	}

	helperAgent, exists := config.Agents["helper"]
	if !exists {
		t.Fatal("expected 'helper' agent to exist")
	}

	if helperAgent.Name != "Helper Agent" {
		t.Errorf("expected helper agent name 'Helper Agent', got '%s'", helperAgent.Name)
	}

	// Only the primary agent (without mode specified) should be in entrypoint
	// The helper agent has mode: subagent, so it should NOT be in entrypoint
	if len(config.Publish.Entrypoint) != 1 || config.Publish.Entrypoint[0] != "primary" {
		t.Errorf("expected entrypoint ['primary'] (subagent should not be included), got %v", config.Publish.Entrypoint)
	}
}

func TestLoadFromDirectory_ModeMixed(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-mode-mixed")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// All three agents should be loaded
	if len(config.Agents) != 3 {
		t.Errorf("expected 3 agents, got %d", len(config.Agents))
	}

	chatAgent, exists := config.Agents["chat"]
	if !exists {
		t.Fatal("expected 'chat' agent to exist")
	}

	if chatAgent.Name != "Chat Agent" {
		t.Errorf("expected chat agent name 'Chat Agent', got '%s'", chatAgent.Name)
	}

	primaryAgent, exists := config.Agents["primary"]
	if !exists {
		t.Fatal("expected 'primary' agent to exist")
	}

	if primaryAgent.Name != "Primary Agent" {
		t.Errorf("expected primary agent name 'Primary Agent', got '%s'", primaryAgent.Name)
	}

	helperAgent, exists := config.Agents["helper"]
	if !exists {
		t.Fatal("expected 'helper' agent to exist")
	}

	if helperAgent.Name != "Helper Agent" {
		t.Errorf("expected helper agent name 'Helper Agent', got '%s'", helperAgent.Name)
	}

	// Both chat and primary should be in entrypoint (mode: chat and mode: primary)
	// The helper agent (mode: subagent) should NOT be in entrypoint
	if len(config.Publish.Entrypoint) != 2 {
		t.Errorf("expected 2 agents in entrypoint, got %d: %v", len(config.Publish.Entrypoint), config.Publish.Entrypoint)
	}

	// Check that both chat and primary are in entrypoint (order may vary)
	entrypointMap := make(map[string]bool)
	for _, agentID := range config.Publish.Entrypoint {
		entrypointMap[agentID] = true
	}

	if !entrypointMap["chat"] {
		t.Error("expected 'chat' agent in entrypoint")
	}

	if !entrypointMap["primary"] {
		t.Error("expected 'primary' agent in entrypoint")
	}

	if entrypointMap["helper"] {
		t.Error("subagent 'helper' should not be in entrypoint")
	}
}

func TestLoadFromDirectory_ModeInvalid_Error(t *testing.T) {
	_, err := loadFromDirectory("testdata/directory-mode-invalid")
	if err == nil {
		t.Fatal("expected error for invalid mode value")
	}

	if !strings.Contains(err.Error(), "invalid mode") {
		t.Errorf("expected error about invalid mode, got: %v", err)
	}

	if !strings.Contains(err.Error(), "invalid_mode") {
		t.Errorf("expected error to mention 'invalid_mode', got: %v", err)
	}

	if !strings.Contains(err.Error(), "agent") {
		t.Errorf("expected error to mention agent name, got: %v", err)
	}
}

func TestParseMarkdownAgent_ModeField(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-mode-chat/agents/agent.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "agent" {
		t.Errorf("expected agent ID 'agent', got '%s'", agentID)
	}

	if agent.Mode != "chat" {
		t.Errorf("expected Mode field to be 'chat', got '%s'", agent.Mode)
	}

	if agent.Agent.Name != "Chat Mode Agent" {
		t.Errorf("expected name 'Chat Mode Agent', got '%s'", agent.Agent.Name)
	}
}

func TestParseMarkdownAgent_NoModeField(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-simple/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	// Mode should be empty string when not specified
	if agent.Mode != "" {
		t.Errorf("expected Mode field to be empty when not specified, got '%s'", agent.Mode)
	}
}

// Tests for permissions field

func TestLoadFromDirectory_WithPermissions(t *testing.T) {
	data, err := loadFromDirectory("testdata/directory-permissions")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var config types.Config
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("error unmarshaling config: %v", err)
	}

	// Check agent loaded
	if len(config.Agents) != 1 {
		t.Errorf("expected 1 agent, got %d", len(config.Agents))
	}

	agent, exists := config.Agents["main"]
	if !exists {
		t.Fatal("expected 'main' agent to exist")
	}

	if agent.Name != "Agent with Permissions" {
		t.Errorf("expected agent name 'Agent with Permissions', got '%s'", agent.Name)
	}

	// Check permissions were parsed correctly
	if agent.Permissions == nil {
		t.Fatal("expected permissions to be set")
	}

	// Test IsAllowed method to verify permissions were compiled correctly
	if !agent.Permissions.IsAllowed("filesystem") {
		t.Error("expected 'filesystem' permission to be allowed")
	}

	if agent.Permissions.IsAllowed("network") {
		t.Error("expected 'network' permission to be denied")
	}

	// Wildcard should allow other permissions (due to "*": allow)
	if !agent.Permissions.IsAllowed("unknown") {
		t.Error("expected 'unknown' permission to be allowed due to wildcard")
	}
}

func TestParseMarkdownAgent_WithPermissions(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-permissions/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	// Check permissions field
	if agent.Permissions == nil {
		t.Fatal("expected permissions to be set")
	}

	// Test permission compilation - order matters!
	// filesystem: allow should be applied
	if !agent.Permissions.IsAllowed("filesystem") {
		t.Error("expected 'filesystem' permission to be allowed")
	}

	// network: deny should be applied
	if agent.Permissions.IsAllowed("network") {
		t.Error("expected 'network' permission to be denied")
	}

	// Last rule wins: "*": allow should allow unknown permissions
	if !agent.Permissions.IsAllowed("unknown_permission") {
		t.Error("expected 'unknown_permission' to be allowed due to wildcard rule")
	}
}

func TestParseMarkdownAgent_PermissionsOrderPreserved(t *testing.T) {
	// Create a temporary test file with specific permission order
	tmpDir := t.TempDir()
	agentsDir := filepath.Join(tmpDir, "agents")
	if err := os.MkdirAll(agentsDir, 0755); err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}

	content := `---
name: Order Test Agent
permissions:
  "*": deny
  specific: allow
---
Testing permission order.
`
	testFile := filepath.Join(agentsDir, "test.md")
	if err := os.WriteFile(testFile, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	agentID, agent, err := parseMarkdownAgent(testFile)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "test" {
		t.Errorf("expected agent ID 'test', got '%s'", agentID)
	}

	if agent.Permissions == nil {
		t.Fatal("expected permissions to be set")
	}

	// Order matters: last matching rule wins
	// "*": deny comes first, then "specific": allow
	// So "specific" should be allowed (overrides wildcard)
	if !agent.Permissions.IsAllowed("specific") {
		t.Error("expected 'specific' permission to be allowed (should override earlier wildcard deny)")
	}

	// Other permissions should be denied by the wildcard
	if agent.Permissions.IsAllowed("other") {
		t.Error("expected 'other' permission to be denied by wildcard")
	}
}

func TestParseMarkdownAgent_ComplexPermissions(t *testing.T) {
	// Create a temporary test file with complex permissions
	tmpDir := t.TempDir()
	agentsDir := filepath.Join(tmpDir, "agents")
	if err := os.MkdirAll(agentsDir, 0755); err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}

	content := `---
name: Complex Permissions Agent
permissions:
  read: allow
  write: deny
  "*": allow
  delete: deny
---
Complex permissions test.
`
	testFile := filepath.Join(agentsDir, "complex.md")
	if err := os.WriteFile(testFile, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	agentID, agent, err := parseMarkdownAgent(testFile)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "complex" {
		t.Errorf("expected agent ID 'complex', got '%s'", agentID)
	}

	if agent.Permissions == nil {
		t.Fatal("expected permissions to be set")
	}

	// Test permission evaluation (last matching rule wins)
	if !agent.Permissions.IsAllowed("read") {
		t.Error("expected 'read' permission to be allowed")
	}

	if agent.Permissions.IsAllowed("write") {
		t.Error("expected 'write' permission to be denied")
	}

	// delete: deny comes after "*": allow, so it should be denied
	if agent.Permissions.IsAllowed("delete") {
		t.Error("expected 'delete' permission to be denied (overrides wildcard)")
	}

	// Permissions not explicitly mentioned should be allowed by wildcard
	if !agent.Permissions.IsAllowed("execute") {
		t.Error("expected 'execute' permission to be allowed by wildcard")
	}
}

func TestParseMarkdownAgent_NoPermissions(t *testing.T) {
	agentID, agent, err := parseMarkdownAgent("testdata/directory-simple/agents/main.md")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if agentID != "main" {
		t.Errorf("expected agent ID 'main', got '%s'", agentID)
	}

	// Permissions should be nil when not specified
	// According to AgentPermissions.IsAllowed, nil permissions allow everything
	if agent.Permissions != nil {
		t.Errorf("expected Permissions field to be nil when not specified, got %v", agent.Permissions)
	}
}
