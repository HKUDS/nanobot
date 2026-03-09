package config

import (
	"strings"
	"testing"
)

func TestParseFrontMatter_Valid(t *testing.T) {
	content := `---
title: My Document
author: John Doe
---
This is the body content.

With multiple lines.
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	expectedYAML := "title: My Document\nauthor: John Doe"
	if string(yaml) != expectedYAML {
		t.Errorf("expected YAML:\n%s\ngot:\n%s", expectedYAML, string(yaml))
	}

	expectedBody := "This is the body content.\n\nWith multiple lines."
	if body != expectedBody {
		t.Errorf("expected body:\n%s\ngot:\n%s", expectedBody, body)
	}
}

func TestParseFrontMatter_NoFrontMatter(t *testing.T) {
	content := `This is just markdown content without front-matter.

No YAML here!
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if yaml != nil {
		t.Errorf("expected nil YAML, got: %s", string(yaml))
	}

	expectedBody := strings.TrimSpace(content)
	if body != expectedBody {
		t.Errorf("expected body:\n%s\ngot:\n%s", expectedBody, body)
	}
}

func TestParseFrontMatter_EmptyFrontMatter(t *testing.T) {
	content := `---
---
This is the body.
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if string(yaml) != "" {
		t.Errorf("expected empty YAML, got: %s", string(yaml))
	}

	expectedBody := "This is the body."
	if body != expectedBody {
		t.Errorf("expected body:\n%s\ngot:\n%s", expectedBody, body)
	}
}

func TestParseFrontMatter_MissingClosing(t *testing.T) {
	content := `---
title: Unclosed
author: Nobody

This should error.
`
	_, _, err := parseFrontMatter([]byte(content))
	if err == nil {
		t.Fatal("expected error for missing closing delimiter")
	}

	if !strings.Contains(err.Error(), "missing closing delimiter") {
		t.Errorf("expected error message about missing closing delimiter, got: %v", err)
	}
}

func TestParseFrontMatter_WindowsLineEndings(t *testing.T) {
	content := "---\r\ntitle: Windows\r\n---\r\nBody with Windows line endings.\r\n"
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	expectedYAML := "title: Windows"
	if string(yaml) != expectedYAML {
		t.Errorf("expected YAML:\n%s\ngot:\n%s", expectedYAML, string(yaml))
	}

	expectedBody := "Body with Windows line endings."
	if body != expectedBody {
		t.Errorf("expected body:\n%s\ngot:\n%s", expectedBody, body)
	}
}

func TestParseFrontMatter_OnlyFrontMatter(t *testing.T) {
	content := `---
key: value
---`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	expectedYAML := "key: value"
	if string(yaml) != expectedYAML {
		t.Errorf("expected YAML:\n%s\ngot:\n%s", expectedYAML, string(yaml))
	}

	if body != "" {
		t.Errorf("expected empty body, got: %s", body)
	}
}

func TestParseFrontMatter_ComplexYAML(t *testing.T) {
	content := `---
name: Test Agent
model: gpt-4
mcpServers:
  - server1
  - server2
tools:
  - tool1
temperature: 0.7
maxTokens: 1000
---
Agent instructions here.
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Just verify we got something reasonable
	if len(yaml) == 0 {
		t.Error("expected non-empty YAML")
	}

	if !strings.Contains(string(yaml), "name: Test Agent") {
		t.Error("expected YAML to contain 'name: Test Agent'")
	}

	if body != "Agent instructions here." {
		t.Errorf("expected body 'Agent instructions here.', got: %s", body)
	}
}

func TestParseFrontMatter_WithPermissions(t *testing.T) {
	content := `---
name: Test Agent
permissions:
  read: allow
  write: deny
  execute: allow
---
Test agent content.
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(yaml) == 0 {
		t.Error("expected non-empty YAML")
	}

	// Verify permissions are in the YAML
	if !strings.Contains(string(yaml), "permissions:") {
		t.Error("expected YAML to contain 'permissions:'")
	}

	if !strings.Contains(string(yaml), "read: allow") {
		t.Error("expected YAML to contain 'read: allow'")
	}

	if !strings.Contains(string(yaml), "write: deny") {
		t.Error("expected YAML to contain 'write: deny'")
	}

	if body != "Test agent content." {
		t.Errorf("expected body 'Test agent content.', got: %s", body)
	}
}

func TestParseFrontMatter_WithWildcardPermission(t *testing.T) {
	content := `---
name: Agent with Wildcard
permissions:
  filesystem: allow
  network: deny
  "*": allow
---
Content here.
`
	yaml, body, err := parseFrontMatter([]byte(content))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(yaml) == 0 {
		t.Error("expected non-empty YAML")
	}

	// Verify wildcard permission is preserved
	yamlStr := string(yaml)
	if !strings.Contains(yamlStr, "permissions:") {
		t.Error("expected YAML to contain 'permissions:'")
	}

	if !strings.Contains(yamlStr, `"*": allow`) && !strings.Contains(yamlStr, `'*': allow`) && !strings.Contains(yamlStr, `*: allow`) {
		t.Errorf("expected YAML to contain wildcard permission, got: %s", yamlStr)
	}

	if body != "Content here." {
		t.Errorf("expected body 'Content here.', got: %s", body)
	}
}
