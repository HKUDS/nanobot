package system

import (
	"context"
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

const testSessionID = "test-session-123"

// testContext creates a context with an MCP session that has the given session ID.
func testContext(t *testing.T) context.Context {
	t.Helper()
	handler := mcp.MessageHandlerFunc(func(ctx context.Context, msg mcp.Message) {})
	serverSession, err := mcp.NewExistingServerSession(context.Background(),
		mcp.SessionState{ID: testSessionID}, handler)
	if err != nil {
		t.Fatalf("failed to create server session: %v", err)
	}
	return mcp.WithSession(context.Background(), serverSession.GetSession())
}

func TestListFileResources(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Change to temp directory
	oldWd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWd)

	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}

	// Create session directory
	sessDir := filepath.Join(tmpDir, sessionsDir, testSessionID)
	if err := os.MkdirAll(sessDir, 0755); err != nil {
		t.Fatal(err)
	}

	// Create test file structure inside session directory
	testFiles := []string{
		"test.txt",
		"test.md",
		"subdir/file.go",
		"subdir/nested/deep.js",
		"subdir/nested/too/deep.txt", // This should not appear (depth > 2)
	}

	for _, f := range testFiles {
		fullPath := filepath.Join(sessDir, f)
		dir := filepath.Dir(fullPath)
		if err := os.MkdirAll(dir, 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(fullPath, []byte("test content"), 0644); err != nil {
			t.Fatal(err)
		}
	}

	// Create files in excluded directories (should not appear)
	excludedDirFiles := []string{
		".git/config",
		".nanobot/status/todo.json",
		"node_modules/package/index.js",
	}

	for _, f := range excludedDirFiles {
		fullPath := filepath.Join(sessDir, f)
		dir := filepath.Dir(fullPath)
		if err := os.MkdirAll(dir, 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(fullPath, []byte("excluded"), 0644); err != nil {
			t.Fatal(err)
		}
	}

	// Create excluded files by name (should not appear)
	excludedNameFiles := []string{
		"nanobot.db",
		"nanobot.db-journal",
		"subdir/nanobot.db-journal", // Also test in subdirectory
	}

	for _, f := range excludedNameFiles {
		fullPath := filepath.Join(sessDir, f)
		dir := filepath.Dir(fullPath)
		if err := os.MkdirAll(dir, 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(fullPath, []byte("excluded db file"), 0644); err != nil {
			t.Fatal(err)
		}
	}

	// Create server and list resources
	server := NewServer("")
	ctx := testContext(t)
	resources, err := server.listFileResources(ctx)
	if err != nil {
		t.Fatalf("listFileResources failed: %v", err)
	}

	// Build map of found resources
	found := make(map[string]mcp.Resource)
	for _, r := range resources {
		path := strings.TrimPrefix(r.URI, "file:///")
		found[path] = r
	}

	// Check that expected files are present
	expectedFiles := []string{
		"test.txt",
		"test.md",
		"subdir/file.go",
		"subdir/nested/deep.js",
	}

	for _, f := range expectedFiles {
		if _, ok := found[f]; !ok {
			t.Errorf("expected file %s not found in resources", f)
			continue
		}
	}

	// Check that excluded directory files are NOT present
	for _, f := range excludedDirFiles {
		if _, ok := found[f]; ok {
			t.Errorf("excluded file %s should not be in resources", f)
		}
	}

	// Check that excluded name files are NOT present
	for _, f := range excludedNameFiles {
		if _, ok := found[f]; ok {
			t.Errorf("excluded file %s should not be in resources", f)
		}
	}

	// Check that too-deep file is NOT present
	if _, ok := found["subdir/nested/too/deep.txt"]; ok {
		t.Error("file at depth > 2 should not be in resources")
	}

	// Verify MIME types
	if r, ok := found["test.txt"]; ok {
		if r.MimeType != "text/plain; charset=utf-8" && r.MimeType != "text/plain" && r.MimeType != "application/octet-stream" {
			t.Logf("MIME type for .txt: %s", r.MimeType)
		}
	}

	if r, ok := found["test.md"]; ok {
		// Note: MIME type for .md varies by system, so we just log it
		t.Logf("MIME type for .md: %s", r.MimeType)
	}

	if r, ok := found["subdir/file.go"]; ok {
		t.Logf("MIME type for .go file: %s", r.MimeType)
	}
}

func TestReadFileResource(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Change to temp directory
	oldWd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWd)

	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}

	// Create session directory
	sessDir := filepath.Join(tmpDir, sessionsDir, testSessionID)
	if err := os.MkdirAll(sessDir, 0755); err != nil {
		t.Fatal(err)
	}

	// Create test file
	testContent := "Hello, world!\nThis is a test file."
	if err := os.WriteFile(filepath.Join(sessDir, "test.txt"), []byte(testContent), 0644); err != nil {
		t.Fatal(err)
	}

	// Create subdirectory file
	if err := os.MkdirAll(filepath.Join(sessDir, "subdir"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sessDir, "subdir/nested.md"), []byte("# Nested file"), 0644); err != nil {
		t.Fatal(err)
	}

	server := NewServer("")
	ctx := testContext(t)

	// Minimal 1x1 PNG (binary); image resources must be returned as base64 Blob, not Text
	minimalPNG := []byte{
		0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
		0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
		0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41, 0x54, 0x08, 0xd7, 0x63, 0xf8, 0xff, 0xff, 0x3f,
		0x00, 0x05, 0xfe, 0x02, 0xfe, 0xdc, 0xcc, 0x59, 0xe7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e,
		0x44, 0xae, 0x42, 0x60, 0x82,
	}
	if err := os.WriteFile(filepath.Join(sessDir, "dot.png"), minimalPNG, 0644); err != nil {
		t.Fatal(err)
	}

	goContent := "package main\n\nfunc main() {}\n"
	if err := os.WriteFile(filepath.Join(sessDir, "test.go"), []byte(goContent), 0644); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name         string
		uri          string
		expectError  bool
		expectedText string
		expectedName string
		expectBlob   bool // image/binary: expect Blob set, Text nil
	}{
		{
			name:         "read root file",
			uri:          "file:///test.txt",
			expectError:  false,
			expectedText: testContent,
			expectedName: "test.txt",
		},
		{
			name:         "read nested file",
			uri:          "file:///subdir/nested.md",
			expectError:  false,
			expectedText: "# Nested file",
			expectedName: "nested.md",
		},
		{
			name:         "read image file returns base64 Blob",
			uri:          "file:///dot.png",
			expectError:  false,
			expectedName: "dot.png",
			expectBlob:   true,
		},
		{
			name:         "read Go file returns resource.text",
			uri:          "file:///test.go",
			expectError:  false,
			expectedText: goContent,
			expectedName: "test.go",
		},
		{
			name:        "nonexistent file",
			uri:         "file:///nonexistent.txt",
			expectError: true,
		},
		{
			name:        "invalid URI scheme",
			uri:         "http:///test.txt",
			expectError: true,
		},
		{
			name:        "empty path",
			uri:         "file:///",
			expectError: true,
		},
		{
			name:        "directory traversal attack",
			uri:         "file:///../../../etc/passwd",
			expectError: true,
		},
		{
			name:        "absolute path attempt",
			uri:         "file:////etc/passwd",
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := server.readFileResource(ctx, tt.uri)

			if tt.expectError {
				if err == nil {
					t.Error("expected error but got none")
				}
				return
			}

			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if result == nil || len(result.Contents) == 0 {
				t.Fatal("expected non-empty contents")
			}

			content := result.Contents[0]
			if tt.expectBlob {
				if content.Blob == nil {
					t.Error("expected Blob to be set for image/binary file")
				}
				if content.Text != nil {
					t.Error("expected Text to be nil for image/binary file")
				}
				if content.Blob != nil {
					decoded, err := base64.StdEncoding.DecodeString(*content.Blob)
					if err != nil {
						t.Errorf("Blob is not valid base64: %v", err)
					} else if len(decoded) != len(minimalPNG) {
						t.Errorf("decoded Blob length = %d, want %d", len(decoded), len(minimalPNG))
					}
				}
			} else {
				if content.Text == nil || *content.Text != tt.expectedText {
					t.Errorf("expected text %q, got %q", tt.expectedText, *content.Text)
				}
			}

			if content.Name != tt.expectedName {
				t.Errorf("expected name %q, got %q", tt.expectedName, content.Name)
			}

			if content.URI != tt.uri {
				t.Errorf("expected URI %q, got %q", tt.uri, content.URI)
			}
		})
	}
}

func TestFileFilter(t *testing.T) {
	tests := []struct {
		name     string
		path     string
		isDir    bool
		expected bool
	}{
		// Root directory
		{name: "root directory", path: ".", isDir: true, expected: true},

		// Specifically excluded hidden directories
		{name: "hidden directory .git", path: ".git", isDir: true, expected: false},
		{name: "hidden directory .nanobot", path: ".nanobot", isDir: true, expected: false},
		{name: "hidden directory .hidden", path: ".hidden", isDir: true, expected: true}, // Changed: now allowed

		// Excluded directories
		{name: "node_modules", path: "node_modules", isDir: true, expected: false},
		{name: "vendor", path: "vendor", isDir: true, expected: false},
		{name: "__pycache__", path: "__pycache__", isDir: true, expected: false},
		{name: ".idea", path: ".idea", isDir: true, expected: false},
		{name: ".vscode", path: ".vscode", isDir: true, expected: false},
		{name: "dist", path: "dist", isDir: true, expected: false},
		{name: "build", path: "build", isDir: true, expected: false},
		{name: "sessions", path: "sessions", isDir: true, expected: false},

		// Normal directories
		{name: "normal directory src", path: "src", isDir: true, expected: true},
		{name: "normal directory subdir", path: "subdir", isDir: true, expected: true},

		// Nested paths with excluded components
		{name: "nested .git", path: "some/path/.git", isDir: true, expected: false},
		{name: "nested node_modules", path: "project/node_modules", isDir: true, expected: false},

		// Files - normal files allowed
		{name: "normal file", path: "test.txt", isDir: false, expected: true},
		{name: "file in subdir", path: "src/main.go", isDir: false, expected: true},

		// Hidden files now allowed (except specifically excluded ones)
		{name: "dotfile .gitignore", path: ".gitignore", isDir: false, expected: true},         // Changed: now allowed
		{name: "dotfile .env", path: ".env", isDir: false, expected: true},                     // Changed: now allowed
		{name: "dotfile in subdir", path: "src/.gitignore", isDir: false, expected: true},      // Changed: now allowed
		{name: "excluded dotfile .DS_Store", path: ".DS_Store", isDir: false, expected: false}, // New: specifically excluded

		// Excluded files by name
		{name: "excluded file nanobot.db", path: "nanobot.db", isDir: false, expected: false},
		{name: "excluded file nanobot.db-journal", path: "nanobot.db-journal", isDir: false, expected: false},
		{name: "excluded file in subdir", path: "subdir/nanobot.db", isDir: false, expected: false},
		{name: "excluded file nested", path: "some/path/nanobot.db-journal", isDir: false, expected: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create mock FileInfo
			info := &mockFileInfo{isDir: tt.isDir}
			result := fileFilter(tt.path, info)

			if result != tt.expected {
				t.Errorf("fileFilter(%q, isDir=%v) = %v, expected %v",
					tt.path, tt.isDir, result, tt.expected)
			}
		})
	}
}

func TestSubscribeFileResource(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Change to temp directory
	oldWd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWd)

	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}

	// Create session directory
	sessDir := filepath.Join(tmpDir, sessionsDir, testSessionID)
	if err := os.MkdirAll(sessDir, 0755); err != nil {
		t.Fatal(err)
	}

	// Create test file in session directory
	if err := os.WriteFile(filepath.Join(sessDir, "test.txt"), []byte("test"), 0644); err != nil {
		t.Fatal(err)
	}

	server := NewServer("")
	ctx := testContext(t)

	tests := []struct {
		name        string
		uri         string
		expectError bool
	}{
		{
			name:        "subscribe to existing file",
			uri:         "file:///test.txt",
			expectError: false,
		},
		{
			name:        "subscribe to nonexistent file",
			uri:         "file:///nonexistent.txt",
			expectError: true,
		},
		{
			name:        "invalid URI",
			uri:         "http:///test.txt",
			expectError: true,
		},
		{
			name:        "empty path",
			uri:         "file:///",
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := server.subscribeFileResource(ctx, tt.uri)

			if tt.expectError {
				if err == nil {
					t.Error("expected error but got none")
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
			}
		})
	}
}

func TestResourcesListCombined(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Change to temp directory
	oldWd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWd)

	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}

	// Create session directory with some test files
	sessDir := filepath.Join(tmpDir, sessionsDir, testSessionID)
	if err := os.MkdirAll(sessDir, 0755); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(filepath.Join(sessDir, "test.txt"), []byte("test"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sessDir, "test.md"), []byte("# Test"), 0644); err != nil {
		t.Fatal(err)
	}

	server := NewServer("")
	ctx := testContext(t)

	// Call the combined resourcesList method
	result, err := server.resourcesList(ctx, mcp.Message{}, mcp.ListResourcesRequest{})
	if err != nil {
		t.Fatalf("resourcesList failed: %v", err)
	}

	// Should have at least 3 resources: todo:///list + 2 files
	if len(result.Resources) < 3 {
		t.Errorf("expected at least 3 resources (todo + files), got %d", len(result.Resources))
	}

	// Check that we have the todo resource
	foundTodo := false
	foundFile := false
	for _, r := range result.Resources {
		if r.URI == "todo:///list" {
			foundTodo = true
		}
		if strings.HasPrefix(r.URI, "file:///") {
			foundFile = true
		}
	}

	if !foundTodo {
		t.Error("expected todo:///list resource")
	}
	if !foundFile {
		t.Error("expected at least one file:/// resource")
	}
}

func TestResourcesReadDispatch(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Change to temp directory
	oldWd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWd)

	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}

	// Create session directory with test file
	sessDir := filepath.Join(tmpDir, sessionsDir, testSessionID)
	if err := os.MkdirAll(sessDir, 0755); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(filepath.Join(sessDir, "test.txt"), []byte("test content"), 0644); err != nil {
		t.Fatal(err)
	}

	server := NewServer("")
	ctx := testContext(t)

	tests := []struct {
		name        string
		uri         string
		expectError bool
	}{
		{
			name:        "read todo resource",
			uri:         "todo:///list",
			expectError: false,
		},
		{
			name:        "read file resource",
			uri:         "file:///test.txt",
			expectError: false,
		},
		{
			name:        "unsupported URI scheme",
			uri:         "http:///test",
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := server.resourcesRead(ctx, mcp.Message{}, mcp.ReadResourceRequest{URI: tt.uri})

			if tt.expectError {
				if err == nil {
					t.Error("expected error but got none")
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if result == nil {
					t.Error("expected non-nil result")
				}
			}
		})
	}
}

// mockFileInfo is a simple mock implementation of os.FileInfo for testing
type mockFileInfo struct {
	isDir bool
}

func (m *mockFileInfo) Name() string       { return "mock" }
func (m *mockFileInfo) Size() int64        { return 0 }
func (m *mockFileInfo) Mode() os.FileMode  { return 0644 }
func (m *mockFileInfo) ModTime() time.Time { return time.Time{} }
func (m *mockFileInfo) IsDir() bool        { return m.isDir }
func (m *mockFileInfo) Sys() interface{}   { return nil }
