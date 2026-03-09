package system

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

// Helper function to create AgentPermissions from a map
func createPermissions(t *testing.T, perms map[string]string) *types.AgentPermissions {
	t.Helper()
	data, err := json.Marshal(perms)
	if err != nil {
		t.Fatalf("failed to marshal permissions: %v", err)
	}
	var ap types.AgentPermissions
	if err := json.Unmarshal(data, &ap); err != nil {
		t.Fatalf("failed to unmarshal permissions: %v", err)
	}
	return &ap
}

func TestConfigSkillsPermissionAppendsInstructions(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"skills": "allow",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: "You are a helpful assistant.",
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	if result.Agent == nil {
		t.Fatal("expected Agent to be set in result")
	}

	instructions := result.Agent.Instructions.Instructions
	if instructions == "You are a helpful assistant." {
		t.Error("expected instructions to be modified, but they were unchanged")
	}

	// Verify the original instructions are still there
	if !strings.Contains(instructions, "You are a helpful assistant.") {
		t.Error("original instructions should be preserved")
	}

	// Verify skills section was added
	if !strings.Contains(instructions, "## Available Skills") {
		t.Error("expected '## Available Skills' header in instructions")
	}

	if !strings.Contains(instructions, "getSkill") {
		t.Error("expected mention of 'getSkill' tool in instructions")
	}
}

func TestConfigSkillsPermissionIncludesSkillDetails(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"skills": "allow",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: "Initial instructions.",
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	instructions := result.Agent.Instructions.Instructions

	// Check for specific skills we know exist
	expectedSkills := []string{"python-scripts", "workflows", "mcp-cli"}
	for _, skillName := range expectedSkills {
		if !strings.Contains(instructions, skillName) {
			t.Errorf("expected skill '%s' to be listed in instructions", skillName)
		}
	}

	// Verify the format includes skill names in bold markdown
	if !strings.Contains(instructions, "**python-scripts**") {
		t.Error("expected skills to be formatted with markdown bold")
	}

	// Verify descriptions are included
	if !strings.Contains(instructions, "Python") {
		t.Error("expected skill descriptions to be included")
	}
}

func TestConfigNoSkillsPermission(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	originalInstructions := "You are a helpful assistant."
	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"*":     "deny",
			"read":  "allow",
			"write": "allow",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: originalInstructions,
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	if result.Agent == nil {
		t.Fatal("expected Agent to be set in result")
	}

	instructions := result.Agent.Instructions.Instructions
	if instructions != originalInstructions {
		t.Errorf("instructions should not be modified when skills permission is not present\ngot: %s\nwant: %s", instructions, originalInstructions)
	}

	// Verify skills section was NOT added
	if strings.Contains(instructions, "## Available Skills") {
		t.Error("skills section should not be added without skills permission")
	}
}

func TestConfigSkillsPermissionDenied(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	originalInstructions := "You are a helpful assistant."
	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"skills": "deny",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: originalInstructions,
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	if result.Agent == nil {
		t.Fatal("expected Agent to be set in result")
	}

	instructions := result.Agent.Instructions.Instructions
	if instructions != originalInstructions {
		t.Errorf("instructions should not be modified when skills permission is denied\ngot: %s\nwant: %s", instructions, originalInstructions)
	}

	// Verify skills section was NOT added
	if strings.Contains(instructions, "## Available Skills") {
		t.Error("skills section should not be added when skills permission is denied")
	}
}

func TestConfigWithUserSkills(t *testing.T) {
	// Use test data directory with user skills
	server := NewServer(testdataDir(t, "with-user-skills"))
	ctx := context.Background()

	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"skills": "allow",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: "Initial instructions.",
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	instructions := result.Agent.Instructions.Instructions

	// Check for built-in skills
	if !strings.Contains(instructions, "python-scripts") {
		t.Error("expected built-in skills to be listed")
	}

	// Check for user-defined skills
	if !strings.Contains(instructions, "my-custom-skill") {
		t.Error("expected user-defined skill 'my-custom-skill' to be listed")
	}

	if !strings.Contains(instructions, "user-skill") {
		t.Error("expected user-defined skill 'user-skill' to be listed")
	}
}

func TestConfigEmptyInstructions(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"skills": "allow",
		}),
		Instructions: types.DynamicInstructions{
			Instructions: "",
		},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	if result.Agent == nil {
		t.Fatal("expected Agent to be set in result")
	}

	instructions := result.Agent.Instructions.Instructions

	// Even with empty initial instructions, skills should be added
	if !strings.Contains(instructions, "## Available Skills") {
		t.Error("expected skills section to be added even with empty initial instructions")
	}
}

func TestConfigNilAgent(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: nil,
	})

	if err != nil {
		t.Fatalf("config() should not error with nil agent: %v", err)
	}

	// Should just return the params unchanged
	if result.Agent != nil {
		t.Error("expected nil agent to remain nil")
	}
}

func TestConfigAddsToolsForPermissions(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	agent := &types.HookAgent{
		Name: "test-agent",
		Permissions: createPermissions(t, map[string]string{
			"read":   "allow",
			"write":  "allow",
			"skills": "allow",
		}),
		MCPServers: []string{},
	}

	result, err := server.config(ctx, types.AgentConfigHook{
		Agent: agent,
	})

	if err != nil {
		t.Fatalf("config() failed: %v", err)
	}

	if result.Agent == nil {
		t.Fatal("expected Agent to be set in result")
	}

	// Check that appropriate tools were added to Tools.
	expectedTools := []string{
		"nanobot.system/read",
		"nanobot.system/write",
		"nanobot.system/getSkill",
		"nanobot.workflow-tools",
	}
	for _, tool := range expectedTools {
		found := false
		for _, t2 := range result.Agent.Tools {
			if t2 == tool {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("expected tool '%s' to be added to Tools", tool)
		}
	}

	if _, ok := result.MCPServers["nanobot.workflow-tools"]; !ok {
		t.Error("expected 'nanobot.workflow-tools' to be present in MCPServers")
	}
}

func TestConfigHook_MCPServerSearch(t *testing.T) {
	s := NewServer("")

	tests := []struct {
		name           string
		envMap         map[string]string
		wantServerName string
		wantURL        string
		wantAuth       string
		shouldExist    bool
	}{
		{
			name: "with both URL and API key",
			envMap: map[string]string{
				"MCP_SERVER_SEARCH_URL":     "https://search.example.com/mcp",
				"MCP_SERVER_SEARCH_API_KEY": "test-key-123",
			},
			wantServerName: "mcp-server-search",
			wantURL:        "https://search.example.com/mcp",
			wantAuth:       "Bearer test-key-123",
			shouldExist:    true,
		},
		{
			name: "with URL but no API key",
			envMap: map[string]string{
				"MCP_SERVER_SEARCH_URL": "https://search.example.com/mcp",
			},
			wantServerName: "mcp-server-search",
			wantURL:        "https://search.example.com/mcp",
			wantAuth:       "",
			shouldExist:    true,
		},
		{
			name:           "without environment variables",
			envMap:         map[string]string{},
			wantServerName: "mcp-server-search",
			shouldExist:    false,
		},
		{
			name: "with empty URL",
			envMap: map[string]string{
				"MCP_SERVER_SEARCH_URL":     "",
				"MCP_SERVER_SEARCH_API_KEY": "test-key-123",
			},
			wantServerName: "mcp-server-search",
			shouldExist:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create context with session and environment
			ctx := context.Background()
			session := mcp.NewEmptySession(ctx)
			session.Set(mcp.SessionEnvMapKey, tt.envMap)
			ctx = mcp.WithSession(ctx, session)

			// Prepare input params
			params := types.AgentConfigHook{
				Agent: &types.HookAgent{
					Name: "Test Agent",
				},
			}

			// Call config hook
			result, err := s.config(ctx, params)
			if err != nil {
				t.Fatalf("config() error = %v", err)
			}

			// Check if MCP server was added
			server, exists := result.MCPServers[tt.wantServerName]

			if exists != tt.shouldExist {
				t.Errorf("MCPServers[%q] exists = %v, want %v", tt.wantServerName, exists, tt.shouldExist)
			}

			if !tt.shouldExist {
				return
			}

			// Verify URL
			if server.URL != tt.wantURL {
				t.Errorf("MCPServers[%q].URL = %q, want %q", tt.wantServerName, server.URL, tt.wantURL)
			}

			// Verify auth header
			if tt.wantAuth != "" {
				authHeader, ok := server.Headers["Authorization"]
				if !ok {
					t.Errorf("MCPServers[%q].Headers[Authorization] not found", tt.wantServerName)
				} else if authHeader != tt.wantAuth {
					t.Errorf("MCPServers[%q].Headers[Authorization] = %q, want %q", tt.wantServerName, authHeader, tt.wantAuth)
				}
			} else {
				if _, ok := server.Headers["Authorization"]; ok {
					t.Errorf("MCPServers[%q].Headers[Authorization] should not be present", tt.wantServerName)
				}
			}
		})
	}
}
