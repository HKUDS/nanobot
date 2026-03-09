package meta

import (
	"context"
	"encoding/base64"
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/fileuri"
	"github.com/nanobot-ai/nanobot/pkg/fswatch"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"gopkg.in/yaml.v3"
	"log/slog"
)

const (
	workflowsDir = "workflows"
	sessionsDir  = "sessions"
)

type workflowMeta struct {
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
	CreatedAt   string `yaml:"createdAt"`
}

func parseWorkflowFrontmatter(content string) (workflowMeta, error) {
	lines := strings.Split(content, "\n")
	if len(lines) < 3 || strings.TrimSpace(lines[0]) != "---" {
		return workflowMeta{}, nil
	}

	endIdx := -1
	for i := 1; i < len(lines); i++ {
		if strings.TrimSpace(lines[i]) == "---" {
			endIdx = i
			break
		}
	}

	if endIdx == -1 {
		return workflowMeta{}, fmt.Errorf("frontmatter missing closing delimiter")
	}

	frontmatterYAML := strings.Join(lines[1:endIdx], "\n")
	var meta workflowMeta
	if err := yaml.Unmarshal([]byte(frontmatterYAML), &meta); err != nil {
		return workflowMeta{}, fmt.Errorf("failed to parse frontmatter: %w", err)
	}

	return meta, nil
}

// resourcesList returns all resources (workflows + cross-session files).
func (s *Server) resourcesList(ctx context.Context, _ mcp.Message, _ mcp.ListResourcesRequest) (*mcp.ListResourcesResult, error) {
	var resources []mcp.Resource

	// Add workflow resources
	workflowResources, err := s.listWorkflowResources(ctx)
	if err != nil {
		slog.Error("failed to list workflow resources", "error", err)
	} else {
		resources = append(resources, workflowResources...)
	}

	// Add cross-session file resources
	fileResources, err := s.listFileResourcesAllSessions(ctx)
	if err != nil {
		slog.Error("failed to list cross-session file resources", "error", err)
	} else {
		resources = append(resources, fileResources...)
	}

	return &mcp.ListResourcesResult{Resources: resources}, nil
}

// resourcesRead reads a resource by URI.
func (s *Server) resourcesRead(ctx context.Context, _ mcp.Message, request mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
	if strings.HasPrefix(request.URI, "workflow:///") {
		return s.readWorkflowResource(ctx, request.URI)
	} else if strings.HasPrefix(request.URI, "file:///") {
		return s.readFileResource(ctx, request.URI)
	}
	return nil, mcp.ErrRPCInvalidParams.WithMessage("unsupported resource URI: %s", request.URI)
}

// resourcesSubscribe subscribes to a resource.
func (s *Server) resourcesSubscribe(ctx context.Context, msg mcp.Message, request mcp.SubscribeRequest) (*mcp.SubscribeResult, error) {
	sessionID, _ := types.GetSessionAndAccountID(ctx)

	// Validate the URI
	if strings.HasPrefix(request.URI, "workflow:///") {
		workflowName := strings.TrimPrefix(request.URI, "workflow:///")
		workflowName = strings.TrimSuffix(workflowName, ".md")
		if workflowName == "" {
			return nil, mcp.ErrRPCInvalidParams.WithMessage("workflow name is required")
		}
		workflowPath := filepath.Join(".", workflowsDir, workflowName+".md")
		if _, err := os.Stat(workflowPath); os.IsNotExist(err) {
			return nil, mcp.ErrRPCInvalidParams.WithMessage("workflow not found: %s", request.URI)
		}
	} else if strings.HasPrefix(request.URI, "file:///") {
		// Verify access: parse sessions/{sessionID}/path and verify account ownership
		if err := s.verifyFileResourceAccess(ctx, request.URI); err != nil {
			return nil, err
		}
	} else {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("unsupported resource URI: %s", request.URI)
	}

	s.subscriptions.Subscribe(sessionID, msg.Session.Root(), request.URI)
	return &mcp.SubscribeResult{}, nil
}

// resourcesUnsubscribe unsubscribes from a resource.
func (s *Server) resourcesUnsubscribe(ctx context.Context, _ mcp.Message, request mcp.UnsubscribeRequest) (*mcp.UnsubscribeResult, error) {
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	s.subscriptions.Unsubscribe(sessionID, request.URI)
	return &mcp.UnsubscribeResult{}, nil
}

// listWorkflowResources reads the workflows/ directory and returns workflow resources.
func (s *Server) listWorkflowResources(ctx context.Context) ([]mcp.Resource, error) {
	workflowsPath := filepath.Join(".", workflowsDir)

	entries, err := os.ReadDir(workflowsPath)
	if err != nil {
		// Directory doesn't exist - return empty list
		return nil, nil
	}

	var resources []mcp.Resource
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".md" {
			continue
		}

		name := strings.TrimSuffix(entry.Name(), ".md")

		contentBytes, err := os.ReadFile(filepath.Join(workflowsPath, entry.Name()))
		if err != nil {
			continue
		}

		meta, err := parseWorkflowFrontmatter(string(contentBytes))
		if err != nil {
			slog.Debug("failed to parse frontmatter for workflow", "workflow", entry.Name(), "error", err)
		}

		resourceMeta := make(map[string]any)
		if meta.Name != "" {
			resourceMeta["name"] = meta.Name
		}
		if meta.CreatedAt != "" {
			resourceMeta["createdAt"] = meta.CreatedAt
		}

		res := mcp.Resource{
			URI:         fmt.Sprintf("workflow:///%s", name),
			Name:        name,
			Description: meta.Description,
			MimeType:    "text/markdown",
		}
		if len(resourceMeta) > 0 {
			res.Meta = resourceMeta
		}

		resources = append(resources, res)
	}

	return resources, nil
}

// readWorkflowResource reads a specific workflow by URI.
func (s *Server) readWorkflowResource(ctx context.Context, uri string) (*mcp.ReadResourceResult, error) {
	workflowName := strings.TrimPrefix(uri, "workflow:///")
	workflowName = strings.TrimSuffix(workflowName, ".md")
	if workflowName == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("workflow name is required")
	}

	workflowPath := filepath.Join(".", workflowsDir, workflowName+".md")
	contentBytes, err := os.ReadFile(workflowPath)
	if err != nil {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("workflow not found: %s", uri)
	}

	content := string(contentBytes)
	meta, err := parseWorkflowFrontmatter(content)
	if err != nil {
		slog.Debug("failed to parse frontmatter for workflow", "workflow", workflowName, "error", err)
	}

	resourceMeta := make(map[string]any)
	if meta.Name != "" {
		resourceMeta["name"] = meta.Name
	}
	if meta.CreatedAt != "" {
		resourceMeta["createdAt"] = meta.CreatedAt
	}

	rc := mcp.ResourceContent{
		URI:      uri,
		Name:     workflowName,
		MIMEType: "text/markdown",
		Text:     &content,
	}
	if len(resourceMeta) > 0 {
		rc.Meta = resourceMeta
	}

	return &mcp.ReadResourceResult{
		Contents: []mcp.ResourceContent{rc},
	}, nil
}

// maxSessionFileDepth is the maximum depth for walking session directories.
const maxSessionFileDepth = 2

// sessionFileFilter determines if a file should be included in session file listing.
func sessionFileFilter(relPath string, info os.FileInfo) bool {
	if relPath == "." {
		return true
	}

	basename := filepath.Base(relPath)

	// Exclude common non-content directories/files
	excludedDirs := map[string]struct{}{
		"node_modules": {},
		".git":         {},
		".nanobot":     {},
	}
	excludedFiles := map[string]struct{}{
		".DS_Store": {},
	}

	if info.IsDir() {
		if _, excluded := excludedDirs[basename]; excluded {
			return false
		}
	} else {
		if _, excluded := excludedFiles[basename]; excluded {
			return false
		}
	}

	return true
}

// listFileResourcesAllSessions lists files across all sessions belonging to the current account.
func (s *Server) listFileResourcesAllSessions(ctx context.Context) ([]mcp.Resource, error) {
	mcpSession := mcp.SessionFromContext(ctx)
	manager, accountID, err := s.getManagerAndAccountID(mcpSession)
	if err != nil {
		return nil, err
	}

	sessions, err := manager.DB.FindByAccount(ctx, "thread", accountID)
	if err != nil {
		return nil, fmt.Errorf("failed to list sessions: %w", err)
	}

	cwd, err := os.Getwd()
	if err != nil {
		return nil, fmt.Errorf("failed to get working directory: %w", err)
	}

	var resources []mcp.Resource
	for _, sess := range sessions {
		sessDir := filepath.Join(cwd, sessionsDir, sess.SessionID)

		// Skip if directory doesn't exist
		if _, err := os.Stat(sessDir); os.IsNotExist(err) {
			continue
		}

		err := filepath.WalkDir(sessDir, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return nil
			}

			relPath, err := filepath.Rel(sessDir, path)
			if err != nil {
				return nil
			}

			if relPath == "." {
				return nil
			}

			depth := len(strings.Split(relPath, string(filepath.Separator)))
			if d.IsDir() && depth > maxSessionFileDepth {
				return filepath.SkipDir
			}

			info, err := d.Info()
			if err != nil {
				return nil
			}
			if !sessionFileFilter(relPath, info) {
				if d.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}

			if d.IsDir() {
				return nil
			}

			mimeType := mime.TypeByExtension(filepath.Ext(relPath))
			if mimeType == "" {
				mimeType = "application/octet-stream"
			}

			// URI format: file:///sessions/{sessionID}/{path}
			uri := fileuri.Encode(filepath.Join(sessionsDir, sess.SessionID, relPath))
			name := fmt.Sprintf("%s/%s", sess.SessionID, relPath)

			resources = append(resources, mcp.Resource{
				URI:      uri,
				Name:     name,
				MimeType: mimeType,
				Size:     info.Size(),
				Annotations: &mcp.Annotations{
					LastModified: info.ModTime(),
				},
			})

			return nil
		})
		if err != nil {
			slog.Error("failed to walk session directory", "path", sessDir, "error", err)
		}
	}

	return resources, nil
}

// verifyFileResourceAccess verifies that the file URI belongs to a session owned by the current account.
func (s *Server) verifyFileResourceAccess(ctx context.Context, relPath string) error {

	// Expected format: sessions/{sessionID}/...
	if !strings.HasPrefix(relPath, sessionsDir+"/") {
		return mcp.ErrRPCInvalidParams.WithMessage("invalid file URI format, expected file:///sessions/{sessionID}/path")
	}

	parts := strings.SplitN(strings.TrimPrefix(relPath, sessionsDir+"/"), "/", 2)
	if len(parts) < 2 || parts[0] == "" || parts[1] == "" {
		return mcp.ErrRPCInvalidParams.WithMessage("invalid file URI format, expected file:///sessions/{sessionID}/path")
	}

	targetSessionID := parts[0]

	mcpSession := mcp.SessionFromContext(ctx)
	manager, accountID, err := s.getManagerAndAccountID(mcpSession)
	if err != nil {
		return err
	}

	// Verify the target session belongs to this account
	if _, err := manager.DB.GetByIDByAccountID(ctx, targetSessionID, accountID); err != nil {
		return mcp.ErrRPCInvalidParams.WithMessage("session not found or access denied: %s", targetSessionID)
	}

	return nil
}

// readFileResource reads a cross-session file resource.
func (s *Server) readFileResource(ctx context.Context, uri string) (*mcp.ReadResourceResult, error) {
	relPath, err := fileuri.Decode(uri)
	if err != nil {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("%v", err)
	}

	if err := s.verifyFileResourceAccess(ctx, relPath); err != nil {
		return nil, err
	}

	// Prevent directory traversal: reject absolute paths and any ".." segments.
	if filepath.IsAbs(relPath) {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("invalid file path")
	}
	for _, segment := range strings.Split(relPath, "/") {
		if segment == ".." {
			return nil, mcp.ErrRPCInvalidParams.WithMessage("invalid file path")
		}
	}

	cwd, err := os.Getwd()
	if err != nil {
		return nil, fmt.Errorf("failed to get working directory: %w", err)
	}

	absPath := filepath.Join(cwd, relPath)

	f, err := os.Open(absPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, mcp.ErrRPCInvalidParams.WithMessage("file not found: %s", uri)
		}
		return nil, fmt.Errorf("failed to open file: %w", err)
	}
	defer f.Close()

	content, err := io.ReadAll(f)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	mimeType := mime.TypeByExtension(filepath.Ext(relPath))
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}
	if i := strings.IndexByte(mimeType, ';'); i >= 0 {
		mimeType = strings.TrimSpace(mimeType[:i])
	}

	rc := mcp.ResourceContent{
		URI:      uri,
		Name:     filepath.Base(relPath),
		MIMEType: mimeType,
	}

	if _, isImage := types.ImageMimeTypes[mimeType]; isImage {
		rc.Blob = new(base64.StdEncoding.EncodeToString(content))
	} else if _, isPDF := types.PDFMimeTypes[mimeType]; isPDF {
		rc.Blob = new(base64.StdEncoding.EncodeToString(content))
	} else {
		rc.Text = new(string(content))
	}

	return &mcp.ReadResourceResult{
		Contents: []mcp.ResourceContent{rc},
	}, nil
}

// ensureWatchers starts the workflow and sessions directory watchers.
func (s *Server) ensureWatchers() error {
	s.watcherOnce.Do(func() {
		// Watch workflows directory
		workflowsPath := filepath.Join(".", workflowsDir)
		if err := os.MkdirAll(workflowsPath, 0755); err != nil {
			s.watcherInitErr = fmt.Errorf("failed to create workflows directory: %w", err)
			return
		}

		workflowFilter := func(relPath string, info os.FileInfo) bool {
			if info.IsDir() {
				return false
			}
			return filepath.Ext(relPath) == ".md"
		}

		s.workflowWatcher = fswatch.NewWatcher(workflowsPath, 0, workflowFilter, s.handleWorkflowEvents)
		if err := s.workflowWatcher.Start(); err != nil {
			s.watcherInitErr = fmt.Errorf("failed to start workflow watcher: %w", err)
			return
		}

		slog.Debug("started meta workflow watcher", "path", workflowsPath)

		// Watch sessions directory
		cwd, err := os.Getwd()
		if err != nil {
			slog.Error("failed to get working directory for sessions watcher", "error", err)
			return
		}

		sessionsPath := filepath.Join(cwd, sessionsDir)
		if err := os.MkdirAll(sessionsPath, 0755); err != nil {
			slog.Error("failed to create sessions directory", "path", sessionsPath, "error", err)
			return
		}

		s.sessionsWatcher = fswatch.NewWatcher(sessionsPath, 3, sessionFileFilter, s.handleSessionFileEvents)
		if err := s.sessionsWatcher.Start(); err != nil {
			slog.Error("failed to start sessions watcher", "error", err)
			return
		}

		slog.Debug("started meta sessions watcher", "path", sessionsPath)
	})

	return s.watcherInitErr
}

// handleWorkflowEvents processes filesystem events from the workflow watcher.
func (s *Server) handleWorkflowEvents(events []fswatch.Event) {
	for _, event := range events {
		workflowName := strings.TrimSuffix(event.Path, ".md")
		uri := fmt.Sprintf("workflow:///%s", workflowName)

		switch event.Type {
		case fswatch.EventDelete:
			s.subscriptions.SendResourceUpdatedNotification(uri)
			s.subscriptions.AutoUnsubscribe(uri)
			s.subscriptions.SendListChangedNotification()
		case fswatch.EventCreate:
			s.subscriptions.SendListChangedNotification()
		case fswatch.EventWrite:
			s.subscriptions.SendResourceUpdatedNotification(uri)
		}
	}
}

// handleSessionFileEvents processes filesystem events from the sessions watcher.
func (s *Server) handleSessionFileEvents(events []fswatch.Event) {
	for _, event := range events {
		// event.Path is relative to the sessions directory, e.g. "{sessionID}/file.txt"
		uri := fileuri.Encode(filepath.Join(sessionsDir, event.Path))

		switch event.Type {
		case fswatch.EventDelete:
			s.subscriptions.SendResourceUpdatedNotification(uri)
			s.subscriptions.AutoUnsubscribe(uri)
			s.subscriptions.SendListChangedNotification()
		case fswatch.EventCreate:
			s.subscriptions.SendListChangedNotification()
		case fswatch.EventWrite:
			s.subscriptions.SendResourceUpdatedNotification(uri)
		}
	}
}
