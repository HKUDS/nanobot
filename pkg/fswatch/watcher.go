package fswatch

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"log/slog"

	"github.com/fsnotify/fsnotify"
)

const debounceTimeout = 100 * time.Millisecond

// mockFileInfo is a simple implementation of os.FileInfo for testing/filtering
type mockFileInfo struct {
	isDir bool
}

func (m *mockFileInfo) Name() string       { return "" }
func (m *mockFileInfo) Size() int64        { return 0 }
func (m *mockFileInfo) Mode() os.FileMode  { return 0 }
func (m *mockFileInfo) ModTime() time.Time { return time.Time{} }
func (m *mockFileInfo) IsDir() bool        { return m.isDir }
func (m *mockFileInfo) Sys() any           { return nil }

// EventType indicates what kind of filesystem event occurred.
type EventType int

const (
	// EventWrite indicates a file was modified.
	EventWrite EventType = iota
	// EventCreate indicates a file was created.
	EventCreate
	// EventDelete indicates a file was deleted or renamed away.
	EventDelete
)

// Event represents a filesystem change event.
type Event struct {
	// Path is the relative path to the changed file (relative to the watched root).
	Path string
	// Type indicates what kind of change occurred.
	Type EventType
}

// FilterFunc decides whether a given path should be watched/reported.
// It receives the relative path and os.FileInfo. Return true to include.
type FilterFunc func(relPath string, info os.FileInfo) bool

// EventHandler is called when filesystem events occur after debouncing.
type EventHandler func(events []Event)

// Watcher watches a directory tree for file changes with configurable depth and filtering.
type Watcher struct {
	rootDir   string
	maxDepth  int
	filter    FilterFunc
	handler   EventHandler
	watcher   *fsnotify.Watcher
	ctx       context.Context
	cancel    context.CancelFunc
	once      sync.Once
	mu        sync.Mutex
	initErr   error
	watchDirs map[string]struct{} // currently watched directories
}

// NewWatcher creates a new Watcher.
//
// Parameters:
//   - rootDir: the root directory to watch
//   - maxDepth: maximum depth of subdirectories to watch (0 = rootDir only, 1 = one level of children, etc.)
//   - filter: a function to decide which files/directories to include (nil means include all)
//   - handler: callback for filesystem events
func NewWatcher(rootDir string, maxDepth int, filter FilterFunc, handler EventHandler) *Watcher {
	return &Watcher{
		rootDir:   rootDir,
		maxDepth:  maxDepth,
		filter:    filter,
		handler:   handler,
		watchDirs: make(map[string]struct{}),
	}
}

// Start initializes the file watcher. It is safe to call multiple times;
// only the first call will start watching.
func (w *Watcher) Start() error {
	w.once.Do(func() {
		watcher, err := fsnotify.NewWatcher()
		if err != nil {
			w.initErr = err
			return
		}

		w.watcher = watcher
		w.ctx, w.cancel = context.WithCancel(context.Background())

		// Walk directory tree and add watches
		if err := w.addWatchRecursive(w.rootDir, 0); err != nil {
			watcher.Close()
			w.initErr = err
			return
		}

		go w.watchLoop()
	})

	return w.initErr
}

// Close stops the watcher and cleans up resources.
func (w *Watcher) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		w.cancel()
	}
	if w.watcher != nil {
		return w.watcher.Close()
	}
	return nil
}

// addWatchRecursive adds watches for the given directory and its subdirectories up to maxDepth.
func (w *Watcher) addWatchRecursive(dir string, currentDepth int) error {
	if currentDepth > w.maxDepth {
		return nil
	}

	// Check if directory exists
	info, err := os.Stat(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	if !info.IsDir() {
		return nil
	}

	// Check filter for directory
	relPath, err := filepath.Rel(w.rootDir, dir)
	if err != nil {
		relPath = dir
	}
	if relPath != "." && w.filter != nil && !w.filter(relPath, info) {
		return nil
	}

	// Add this directory to the watcher
	if err := w.watcher.Add(dir); err != nil {
		return err
	}

	w.mu.Lock()
	w.watchDirs[dir] = struct{}{}
	w.mu.Unlock()

	// Walk subdirectories
	if currentDepth < w.maxDepth {
		entries, err := os.ReadDir(dir)
		if err != nil {
			return nil // Ignore errors reading directory contents
		}
		for _, entry := range entries {
			if entry.IsDir() {
				subDir := filepath.Join(dir, entry.Name())
				if err := w.addWatchRecursive(subDir, currentDepth+1); err != nil {
					// Log but continue - don't fail the whole watch setup for one subdir
					slog.Error("failed to watch subdirectory", "path", subDir, "error", err)
				}
			}
		}
	}

	return nil
}

// depthOf returns the depth of a path relative to the root directory.
func (w *Watcher) depthOf(path string) int {
	relPath, err := filepath.Rel(w.rootDir, path)
	if err != nil {
		return -1
	}
	if relPath == "." {
		return 0
	}
	return len(strings.Split(relPath, string(filepath.Separator)))
}

// watchLoop processes file system events and sends notifications.
func (w *Watcher) watchLoop() {
	// Debounce map: filename -> event
	type pendingEvent struct {
		path      string
		eventType EventType
		time      time.Time
	}
	pending := make(map[string]*pendingEvent)
	pendingMu := sync.Mutex{}

	ticker := time.NewTicker(debounceTimeout)
	defer ticker.Stop()

	for {
		select {
		case <-w.ctx.Done():
			return

		case event, ok := <-w.watcher.Events:
			if !ok {
				return
			}

			// Get relative path
			relPath, err := filepath.Rel(w.rootDir, event.Name)
			if err != nil {
				continue
			}

			// Check if this is a directory event (for managing watches)
			info, statErr := os.Stat(event.Name)

			// Handle new directories: add them to the watcher if within depth
			if statErr == nil && info.IsDir() && event.Op.Has(fsnotify.Create) {
				depth := w.depthOf(event.Name)
				if depth >= 0 && depth <= w.maxDepth {
					if w.filter == nil || w.filter(relPath, info) {
						if err := w.addWatchRecursive(event.Name, depth); err != nil {
							slog.Error("failed to watch new directory", "path", event.Name, "error", err)
						}
						// Send list_changed since new directory means new potential files
						w.handler([]Event{{Path: relPath, Type: EventCreate}})
					}
				}
				continue
			}

			// Skip if directory (we only report file events)
			if statErr == nil && info.IsDir() {
				continue
			}

			// Apply filter for files
			if w.filter != nil {
				// For deleted files, we can't stat them, so we need to infer if it's a file
				if statErr != nil {
					if event.Op.Has(fsnotify.Remove | fsnotify.Rename) {
						// For deleted files, create a mock fileinfo that assumes it's a file
						// We check if any parent directory component should be excluded
						mockInfo := &mockFileInfo{isDir: false}
						if !w.filter(relPath, mockInfo) {
							continue
						}
					} else {
						continue
					}
				} else if !w.filter(relPath, info) {
					continue
				}
			}

			if !event.Op.Has(fsnotify.Write | fsnotify.Create | fsnotify.Remove | fsnotify.Rename) {
				continue
			}

			// Determine event type
			var evType EventType
			if event.Op.Has(fsnotify.Remove | fsnotify.Rename) {
				evType = EventDelete
			} else if event.Op.Has(fsnotify.Create) {
				evType = EventCreate
			} else {
				evType = EventWrite
			}

			// Remove and create events are handled immediately
			if evType == EventDelete || evType == EventCreate {
				w.handler([]Event{{Path: relPath, Type: evType}})
				pendingMu.Lock()
				delete(pending, event.Name)
				pendingMu.Unlock()
			} else {
				// Debounce write events
				pendingMu.Lock()
				pending[event.Name] = &pendingEvent{
					path:      relPath,
					eventType: evType,
					time:      time.Now(),
				}
				pendingMu.Unlock()
			}

		case err, ok := <-w.watcher.Errors:
			if !ok {
				return
			}
			slog.Error("file watcher error", "error", err)

		case <-ticker.C:
			// Process debounced events
			now := time.Now()
			var events []Event
			pendingMu.Lock()
			for name, pe := range pending {
				if now.Sub(pe.time) >= debounceTimeout {
					events = append(events, Event{Path: pe.path, Type: pe.eventType})
					delete(pending, name)
				}
			}
			pendingMu.Unlock()

			if len(events) > 0 {
				w.handler(events)
			}
		}
	}
}
