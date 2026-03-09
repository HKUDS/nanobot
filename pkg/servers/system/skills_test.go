package system

import (
	"context"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// testdataDir returns the absolute path to the testdata directory
func testdataDir(t *testing.T, subdir string) string {
	t.Helper()
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("failed to get caller info")
	}
	return filepath.Join(filepath.Dir(filename), "testdata", subdir)
}

func TestListSkills(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	result, err := server.listSkills(ctx, struct{}{})
	if err != nil {
		t.Fatalf("listSkills() failed: %v", err)
	}
	if result == nil {
		t.Fatal("listSkills() returned nil result")
	}

	// We should have at least the 3 skills we know about
	if len(result.Skills) < 3 {
		t.Errorf("expected at least 3 skills, got %d", len(result.Skills))
	}

	// Verify the skills have names, display names, and descriptions
	skillNames := make(map[string]bool)
	for _, skill := range result.Skills {
		if skill.Name == "" {
			t.Error("skill name should not be empty")
		}
		if skill.DisplayName == "" {
			t.Error("skill display name should not be empty")
		}
		if skill.Description == "" {
			t.Error("skill description should not be empty")
		}
		skillNames[skill.Name] = true
	}

	// Check for expected skills
	expectedSkills := []string{"python-scripts", "workflows", "mcp-cli"}
	for _, expected := range expectedSkills {
		if !skillNames[expected] {
			t.Errorf("should have %s skill", expected)
		}
	}
}

func TestListSkillsWithUserSkills(t *testing.T) {
	server := NewServer(testdataDir(t, "with-user-skills"))
	ctx := context.Background()

	result, err := server.listSkills(ctx, struct{}{})
	if err != nil {
		t.Fatalf("listSkills() failed: %v", err)
	}
	if result == nil {
		t.Fatal("listSkills() returned nil result")
	}

	// Verify user skill is included
	skillsByName := make(map[string]Skill)
	for _, skill := range result.Skills {
		skillsByName[skill.Name] = skill
	}

	// Check user skills are present with correct display names
	if skill, ok := skillsByName["user-skill"]; !ok {
		t.Error("should have user-skill")
	} else if skill.DisplayName != "User-Defined Skill" {
		t.Errorf("user-skill display name = %q, want %q", skill.DisplayName, "User-Defined Skill")
	}

	if skill, ok := skillsByName["my-custom-skill"]; !ok {
		t.Error("should have my-custom-skill")
	} else if skill.DisplayName != "Custom Skill" {
		t.Errorf("my-custom-skill display name = %q, want %q", skill.DisplayName, "Custom Skill")
	}

	// Built-in skills should still be there
	if _, ok := skillsByName["python-scripts"]; !ok {
		t.Error("should have python-scripts skill")
	}
}

func TestListSkillsUserOverridesBuiltin(t *testing.T) {
	server := NewServer(testdataDir(t, "with-override"))
	ctx := context.Background()

	result, err := server.listSkills(ctx, struct{}{})
	if err != nil {
		t.Fatalf("listSkills() failed: %v", err)
	}
	if result == nil {
		t.Fatal("listSkills() returned nil result")
	}

	// Find the workflows skill and verify it has the overridden display name and description
	var workflowsSkill *Skill
	for _, skill := range result.Skills {
		if skill.Name == "workflows" {
			workflowsSkill = &skill
			break
		}
	}

	if workflowsSkill == nil {
		t.Fatal("workflows skill should exist")
	}

	expectedDisplayName := "Custom Workflows"
	if workflowsSkill.DisplayName != expectedDisplayName {
		t.Errorf("workflows skill display name = %q, want %q", workflowsSkill.DisplayName, expectedDisplayName)
	}

	expectedDesc := "My custom workflows skill that overrides the built-in"
	if workflowsSkill.Description != expectedDesc {
		t.Errorf("workflows skill description = %q, want %q", workflowsSkill.Description, expectedDesc)
	}
}

func TestListSkillsMissingDirectory(t *testing.T) {
	// Use a non-existent directory - should not error
	server := NewServer("/non/existent/directory")
	ctx := context.Background()

	result, err := server.listSkills(ctx, struct{}{})
	if err != nil {
		t.Fatalf("listSkills() should not error on missing directory: %v", err)
	}
	if result == nil {
		t.Fatal("listSkills() returned nil result")
	}

	// Should still have built-in skills
	if len(result.Skills) < 3 {
		t.Errorf("should have at least 3 built-in skills, got %d", len(result.Skills))
	}
}

func TestListSkillsEmptyDirectory(t *testing.T) {
	// Use a directory with an empty skills subdirectory
	server := NewServer(testdataDir(t, "empty-skills"))
	ctx := context.Background()

	result, err := server.listSkills(ctx, struct{}{})
	if err != nil {
		t.Fatalf("listSkills() failed: %v", err)
	}
	if result == nil {
		t.Fatal("listSkills() returned nil result")
	}

	// Should still have built-in skills
	if len(result.Skills) < 3 {
		t.Errorf("should have at least 3 built-in skills, got %d", len(result.Skills))
	}
}

func TestGetSkill(t *testing.T) {
	server := NewServer("")
	ctx := context.Background()

	tests := []struct {
		name          string
		skillName     string
		expectError   bool
		shouldContain string
	}{
		{
			name:          "get skill without extension",
			skillName:     "python-scripts",
			expectError:   false,
			shouldContain: "name: python-scripts",
		},
		{
			name:          "get skill with extension",
			skillName:     "python-scripts.md",
			expectError:   false,
			shouldContain: "name: python-scripts",
		},
		{
			name:          "get workflows skill",
			skillName:     "workflows",
			expectError:   false,
			shouldContain: "name: workflows",
		},
		{
			name:          "get mcp-cli skill",
			skillName:     "mcp-cli",
			expectError:   false,
			shouldContain: "name: mcp-cli",
		},
		{
			name:        "nonexistent skill",
			skillName:   "nonexistent-skill",
			expectError: true,
		},
		{
			name:        "empty skill name",
			skillName:   "",
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			content, err := server.getSkill(ctx, GetSkillParams{Name: tt.skillName})

			if tt.expectError {
				if err == nil {
					t.Error("expected error but got none")
				}
			} else {
				if err != nil {
					t.Fatalf("getSkill() failed: %v", err)
				}
				if content == "" {
					t.Error("expected non-empty content")
				}
				if tt.shouldContain != "" && !strings.Contains(content, tt.shouldContain) {
					t.Errorf("content should contain %q", tt.shouldContain)
				}
				// Verify it starts with frontmatter
				if len(content) < 3 || content[0:3] != "---" {
					t.Error("content should start with frontmatter")
				}
			}
		})
	}
}

func TestGetSkillUserSkill(t *testing.T) {
	server := NewServer(testdataDir(t, "with-user-skills"))
	ctx := context.Background()

	content, err := server.getSkill(ctx, GetSkillParams{Name: "my-custom-skill"})
	if err != nil {
		t.Fatalf("getSkill() failed: %v", err)
	}
	if !strings.Contains(content, "name: Custom Skill") {
		t.Error("content should contain 'name: Custom Skill'")
	}
	if !strings.Contains(content, "Custom content here.") {
		t.Error("content should contain 'Custom content here.'")
	}
}

func TestGetSkillUserOverridesBuiltin(t *testing.T) {
	server := NewServer(testdataDir(t, "with-override"))
	ctx := context.Background()

	content, err := server.getSkill(ctx, GetSkillParams{Name: "workflows"})
	if err != nil {
		t.Fatalf("getSkill() failed: %v", err)
	}
	if !strings.Contains(content, "name: Custom Workflows") {
		t.Error("content should contain 'name: Custom Workflows'")
	}
	if !strings.Contains(content, "My custom workflows skill that overrides the built-in") {
		t.Error("content should contain overridden description")
	}
	if !strings.Contains(content, "This overrides the built-in workflows skill.") {
		t.Error("content should contain overridden content")
	}
}

func TestGetSkillFallsBackToBuiltin(t *testing.T) {
	// Use the with-user-skills directory which doesn't have a workflows.md file
	server := NewServer(testdataDir(t, "with-user-skills"))
	ctx := context.Background()

	content, err := server.getSkill(ctx, GetSkillParams{Name: "workflows"})
	if err != nil {
		t.Fatalf("getSkill() failed: %v", err)
	}
	// Should get the built-in workflows skill
	if !strings.Contains(content, "name: workflows") {
		t.Error("content should contain 'name: workflows'")
	}
	if !strings.Contains(content, "Workflows are for repeatable tasks") {
		t.Error("content should contain built-in workflows skill content")
	}
}

func TestParseFrontmatter(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		expectError bool
		expected    map[string]string
	}{
		{
			name: "valid frontmatter",
			content: `---
name: test-skill
description: A test skill
---

# Content here`,
			expectError: false,
			expected: map[string]string{
				"name":        "test-skill",
				"description": "A test skill",
			},
		},
		{
			name: "frontmatter with extra fields",
			content: `---
name: test-skill
description: A test skill
author: test
---

Content`,
			expectError: false,
			expected: map[string]string{
				"name":        "test-skill",
				"description": "A test skill",
				"author":      "test",
			},
		},
		{
			name:        "no frontmatter",
			content:     "Just regular content",
			expectError: true,
		},
		{
			name: "unclosed frontmatter",
			content: `---
name: test
description: test`,
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := parseFrontmatter(tt.content)

			if tt.expectError {
				if err == nil {
					t.Error("expected error but got none")
				}
			} else {
				if err != nil {
					t.Fatalf("parseFrontmatter() failed: %v", err)
				}
				if len(result) != len(tt.expected) {
					t.Errorf("got %d fields, want %d", len(result), len(tt.expected))
				}
				for k, v := range tt.expected {
					if result[k] != v {
						t.Errorf("field %q = %q, want %q", k, result[k], v)
					}
				}
			}
		})
	}
}
