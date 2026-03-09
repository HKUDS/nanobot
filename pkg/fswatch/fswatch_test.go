package fswatch

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestWatcherBasic(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Create a test file
	testFile := filepath.Join(tmpDir, "test.txt")
	if err := os.WriteFile(testFile, []byte("initial"), 0644); err != nil {
		t.Fatal(err)
	}

	// Track events
	eventCh := make(chan Event, 2)
	handler := func(events []Event) {
		for _, event := range events {
			eventCh <- event
		}
	}

	// Create watcher (depth 0, no subdirectories)
	watcher := NewWatcher(tmpDir, 0, nil, handler)
	if err := watcher.Start(); err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()

	// Modify the file
	if err := os.WriteFile(testFile, []byte("modified"), 0644); err != nil {
		t.Fatal(err)
	}

	deadline := time.After(2 * time.Second)
	for {
		select {
		case event := <-eventCh:
			if event.Type == EventWrite && event.Path == "test.txt" {
				return
			}
		case <-deadline:
			t.Fatal("timed out waiting for write event for test.txt")
		}
	}
}

func TestWatcherFilter(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Track events
	var (
		mu     sync.Mutex
		events []Event
	)
	handler := func(evts []Event) {
		mu.Lock()
		defer mu.Unlock()
		events = append(events, evts...)
	}

	// Create filter that only accepts .md files
	filter := func(relPath string, info os.FileInfo) bool {
		if info.IsDir() {
			return true
		}
		return filepath.Ext(relPath) == ".md"
	}

	// Create watcher
	watcher := NewWatcher(tmpDir, 0, filter, handler)
	if err := watcher.Start(); err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()

	// Give watcher time to start
	time.Sleep(100 * time.Millisecond)

	// Create .md file (should be reported)
	mdFile := filepath.Join(tmpDir, "test.md")
	if err := os.WriteFile(mdFile, []byte("markdown"), 0644); err != nil {
		t.Fatal(err)
	}

	// Create .txt file (should be filtered out)
	txtFile := filepath.Join(tmpDir, "test.txt")
	if err := os.WriteFile(txtFile, []byte("text"), 0644); err != nil {
		t.Fatal(err)
	}

	// Wait for events
	time.Sleep(200 * time.Millisecond)

	// Check events
	mu.Lock()
	defer mu.Unlock()

	// Should only see .md file
	var foundMd, foundTxt bool
	for _, evt := range events {
		if evt.Path == "test.md" {
			foundMd = true
		}
		if evt.Path == "test.txt" {
			foundTxt = true
		}
	}

	if !foundMd {
		t.Error("expected event for test.md")
	}
	if foundTxt {
		t.Error("should not receive event for test.txt (filtered)")
	}
}

func TestWatcherRecursive(t *testing.T) {
	// Create temp directory
	tmpDir := t.TempDir()

	// Create subdirectory
	subDir := filepath.Join(tmpDir, "subdir")
	if err := os.MkdirAll(subDir, 0755); err != nil {
		t.Fatal(err)
	}

	// Track events
	var (
		mu     sync.Mutex
		events []Event
	)
	handler := func(evts []Event) {
		mu.Lock()
		defer mu.Unlock()
		events = append(events, evts...)
	}

	// Create watcher with depth 1 (watches subdirectories)
	watcher := NewWatcher(tmpDir, 1, nil, handler)
	if err := watcher.Start(); err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()

	// Give watcher time to start
	time.Sleep(100 * time.Millisecond)

	// Create file in subdirectory
	subFile := filepath.Join(subDir, "test.txt")
	if err := os.WriteFile(subFile, []byte("test"), 0644); err != nil {
		t.Fatal(err)
	}

	// Wait for events
	time.Sleep(200 * time.Millisecond)

	// Check events
	mu.Lock()
	defer mu.Unlock()

	// Should see the file creation in subdirectory
	var found bool
	for _, evt := range events {
		if evt.Path == filepath.Join("subdir", "test.txt") {
			found = true
			break
		}
	}

	if !found {
		t.Errorf("expected event for subdir/test.txt, got events: %+v", events)
	}
}

func TestSubscriptionManager(t *testing.T) {
	sm := NewSubscriptionManager(t.Context())

	// Create mock session (we can't easily create a real one in tests)
	// Just test the subscribe/unsubscribe logic
	sessionID := "test-session"

	// Subscribe to a URI
	sm.Subscribe(sessionID, nil, "test:///resource")

	// Unsubscribe
	sm.Unsubscribe(sessionID, "test:///resource")

	// Auto-unsubscribe
	sm.Subscribe(sessionID, nil, "test:///resource2")
	sm.AutoUnsubscribe("test:///resource2")

	// Test passes if no panics occur
}
