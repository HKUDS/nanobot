package system

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	htmltomarkdown "github.com/JohannesKaufmann/html-to-markdown/v2"
	"github.com/nanobot-ai/nanobot/pkg/fswatch"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/version"
	"golang.org/x/net/html"
	"log/slog"
)

const (
	maxResponseSize    = 5 * 1024 * 1024 // 5MB
	defaultHTTPTimeout = 30 * time.Second
	maxHTTPTimeout     = 120 * time.Second
	defaultBashTimeout = 120 * time.Second
	maxBashTimeout     = 600 * time.Second
	sessionsDir        = "sessions"
)

// sessionDir returns the absolute path for a session's working directory.
func sessionDir(sessionID string) string {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	return filepath.Join(cwd, sessionsDir, sessionID)
}

// ensureSessionDir lazily creates and returns the session directory.
func ensureSessionDir(sessionID string) (string, error) {
	dir := sessionDir(sessionID)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", fmt.Errorf("failed to create session directory: %w", err)
	}
	return dir, nil
}

type Server struct {
	configDir      string
	tools          mcp.ServerTools
	subscriptions  *fswatch.SubscriptionManager
	fileWatchers   map[string]*fswatch.Watcher
	fileWatchersMu sync.Mutex
}

func NewServer(configDir string) *Server {
	s := &Server{
		configDir:     configDir,
		subscriptions: fswatch.NewSubscriptionManager(context.Background()),
		fileWatchers:  make(map[string]*fswatch.Watcher),
	}

	s.tools = mcp.NewServerTools(
		// Config tool to setup system tools based on permissions
		mcp.NewServerTool("config", "Modifies the agent config based on the file system", s.config),
		// Bash tool
		mcp.NewServerTool("bash", `Executes a given bash command in a persistent shell session with optional timeout, ensuring proper handling and security measures.

IMPORTANT: This tool is for terminal operations like git, npm, docker, etc. DO NOT use it for file operations (reading, writing, editing, searching, finding files) - use the specialized tools for this instead.

Before executing the command, please follow these steps:

1. Directory Verification:
   - If the command will create new directories or files, first use `+"`ls`"+` to verify the parent directory exists and is the correct location
   - For example, before running "mkdir foo/bar", first use `+"`ls foo`"+` to check that "foo" exists and is the intended parent directory

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes (e.g., cd "path with spaces/file.txt")
   - Examples of proper quoting:
     - cd "/Users/name/My Documents" (correct)
     - cd /Users/name/My Documents (incorrect - will fail)
     - python "/path/with spaces/script.py" (correct)
     - python /path/with spaces/script.py (incorrect - will fail)
   - After ensuring proper quoting, execute the command.
   - Capture the output of the command.

Usage notes:
  - The command argument is required.
  - You can specify an optional timeout in milliseconds (up to 600000ms / 10 minutes). If not specified, commands will timeout after 120000ms (2 minutes).
  - It is very helpful if you write a clear, concise description of what this command does in 5-10 words.
  - If the output exceeds 30000 characters, output will be truncated before being returned to you.

  - Avoid using Bash with the "find", "ggrep", "cat", "head", "tail", "sed", "awk", or "echo" commands, unless explicitly instructed or when these commands are truly necessary for the task. Instead, always prefer using the dedicated tools for these commands:
    - File search: Use Glob (NOT find or ls)
    - Content search: Use Grep (NOT grep or rg)
    - Read files: Use Read (NOT cat/head/tail)
    - Edit files: Use Edit (NOT sed/awk)
    - Write files: Use Write (NOT echo >/cat <<EOF)
    - Communication: Output text directly (NOT echo/printf)
  - When issuing multiple commands:
    - If the commands are independent and can run in parallel, make multiple Bash tool calls in a single message. For example, if you need to run "git status" and "git diff", send a single message with two Bash tool calls in parallel.
    - If the commands depend on each other and must run sequentially, use a single Bash call with '&&' to chain them together (e.g., `+"`git add . && git commit -m \"message\" && git push`"+`). For instance, if one operation must complete before another starts (like mkdir before cp, Write before Bash for git operations, or git add before git commit), run these operations sequentially instead.
    - Use ';' only when you need to run commands sequentially but don't care if earlier commands fail
    - DO NOT use newlines to separate commands (newlines are ok in quoted strings)
  - AVOID using `+"`cd <directory> && <command>`"+`. Use the `+"`workdir`"+` parameter to change directories instead.

The working directory defaults to your session directory. Always use absolute file paths. The session directory path is provided in your system prompt.`, s.bash),
		// Read tool
		mcp.NewServerTool("read", `Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- Always use absolute file paths. The session directory path is provided in your system prompt.
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
- You can read image files using this tool.
- This tool can read PDF files (.pdf). For large PDFs (more than 10 pages), you MUST provide the pages parameter to read specific page ranges (e.g., pages: "1-5"). Reading a large PDF without the pages parameter will fail. Maximum 10 pages per request.`, s.read),
		// Write tool
		mcp.NewServerTool("write", `Writes a file to the local filesystem.

Usage:
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.

Always use absolute file paths. The session directory path is provided in your system prompt.`, s.write),
		// Edit tool
		mcp.NewServerTool("edit", `Performs exact string replacements in files.

Usage:
- You must use your `+"`Read`"+` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `+"`old_string`"+` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `+"`replace_all`"+` to change every instance of `+"`old_string`"+`.
- Use `+"`replace_all`"+` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.

Always use absolute file paths. The session directory path is provided in your system prompt.`, s.edit),
		// Glob tool
		mcp.NewServerTool("glob", `- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Task tool instead
- You can call multiple tools in a single response. It is always better to speculatively perform multiple searches in parallel if they are potentially useful.

The search path defaults to your session directory. Use absolute paths for searching elsewhere. The session directory path is provided in your system prompt.`, s.glob),
		// Grep tool
		mcp.NewServerTool("grep", `A powerful search tool built on ripgrep

  Usage:
  - ALWAYS use Grep for search tasks. NEVER invoke `+"`grep`"+` or `+"`rg`"+` as a Bash command. The Grep tool has been optimized for correct permissions and access.
  - Supports full regex syntax (e.g., "log.*Error", "function\s+\w+")
  - Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter (e.g., "js", "py", "rust")
  - Output modes: "content" shows matching lines, "files_with_matches" shows only file paths (default), "count" shows match counts
  - Use Task tool for open-ended searches requiring multiple rounds
  - Pattern syntax: Uses ripgrep (not grep) - literal braces need escaping (use `+"`interface\\{\\}`"+` to find `+"`interface{}`"+` in Go code)
  - Multiline matching: By default patterns match within single lines only. For cross-line patterns like `+"`struct \\{[\\s\\S]*?field`"+`, use `+"`multiline: true`"+`

The search path defaults to your session directory. Use absolute paths for searching elsewhere. The session directory path is provided in your system prompt.`, s.grep),
		// TodoWrite tool
		mcp.NewServerTool("todoWrite", `Use this tool to create and manage a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.

## When to Use This Tool
Use this tool proactively in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. After receiving new instructions - Immediately capture user requirements as todos
6. When you start working on a task - Mark it as in_progress BEFORE beginning work. Ideally you should only have one todo as in_progress at a time
7. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation

## When NOT to Use This Tool

Skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no organizational benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial task to do. In this case you are better off just doing the task directly.

## Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (limit to ONE task at a time)
   - completed: Task finished successfully

   **IMPORTANT**: Task descriptions must have two forms:
   - content: The imperative form describing what needs to be done (e.g., "Run tests", "Build the project")
   - activeForm: The present continuous form shown during execution (e.g., "Running tests", "Building the project")

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Exactly ONE task must be in_progress at any time (not less, not more)
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - Tests are failing
     - Implementation is partial
     - You encountered unresolved errors
     - You couldn't find necessary files or dependencies

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names
   - Always provide both forms:
     - content: "Fix authentication bug"
     - activeForm: "Fixing authentication bug"

When in doubt, use this tool. Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully.
`, s.todoWrite),
		// WebFetch tool
		mcp.NewServerTool("webFetch", `
- Fetches content from a specified URL and returns it in the requested format
- Takes a URL and format as input (text, markdown, or html)
- Automatically converts HTML to the requested format
- Optional prompt parameter for specifying what information to extract
- Use this tool when you need to retrieve web content

Usage notes:
  - IMPORTANT: If an MCP-provided web fetch tool is available, prefer using that tool instead of this one, as it may have fewer restrictions. All MCP-provided tools start with "mcp__".
  - The URL must be a fully-formed valid URL (http:// or https://)
  - HTTP URLs will be automatically upgraded to HTTPS when possible
  - Maximum response size: 5MB
  - Default timeout: 30 seconds, maximum: 120 seconds
  - This tool is read-only and does not modify any files
  - When a URL redirects to a different host, the tool will inform you and provide the redirect URL`, s.webFetch),
		// Question tool
		mcp.NewServerTool("askUserQuestion", `Use this tool when you need to ask the user questions during execution. This allows you to:
1. Gather user preferences or requirements
2. Clarify ambiguous instructions
3. Get decisions on implementation choices as you work
4. Offer choices to the user about what direction to take.

Parameters:
- questions (required, array, min 1): Array of question objects, each with:
  - question (required, string): The full question text to display to the user
  - header (required, string): Short label (e.g. "Language", "Framework") used to identify the question in responses
  - multiple (optional, bool, default false): Set to true to allow the user to select more than one option
  - options (required, array, min 1): Available choices, each with:
    - label (required, string): Display text for the option
    - description (optional, string): Explanation of what this option means

Usage notes:
- A "Type your own answer" option is always added automatically; don't include "Other" or catch-all options
- Answers are returned as arrays of labels; set multiple: true to allow selecting more than one
- If you recommend a specific option, make that the first option in the list and add "(Recommended)" at the end of the label`, s.question),
		// Skills tools
		mcp.NewServerTool("listSkills", "List all available skills with their names and descriptions", s.listSkills),
		mcp.NewServerTool("getSkill", "Get the full content of a specific skill by name (with or without .md extension)", s.getSkill),
		// File management tools
		mcp.NewServerTool("uploadFile", `Uploads a file to the session directory from base64-encoded content.

Parameters:
- name (required): Filename or relative path (e.g., "photo.png" or "uploads/doc.pdf")
- blob (required): Base64-encoded file content
- mimeType (optional): MIME type of the file (auto-detected from extension if omitted)

Returns a resource_link with the file:/// URI of the uploaded file.`, s.uploadFile),
		mcp.NewServerTool("deleteFile", `Deletes a file or directory in the session directory.

Parameters:
- uri (required): The file:/// URI of the file to delete

For directories, all contents are removed recursively.`, s.deleteFile),
	)

	return s
}

// Close cleans up resources
func (s *Server) Close() error {
	s.fileWatchersMu.Lock()
	defer s.fileWatchersMu.Unlock()
	var errs []error
	for _, w := range s.fileWatchers {
		if err := w.Close(); err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) > 0 {
		return errs[0]
	}
	return nil
}

func (s *Server) OnMessage(ctx context.Context, msg mcp.Message) {
	switch msg.Method {
	case "initialize":
		mcp.Invoke(ctx, msg, s.initialize)
	case "notifications/initialized":
		// nothing to do
	case "notifications/cancelled":
		mcp.HandleCancelled(ctx, msg)
	case "tools/list":
		mcp.Invoke(ctx, msg, s.tools.List)
	case "tools/call":
		mcp.Invoke(ctx, msg, s.tools.Call)
	case "resources/list":
		mcp.Invoke(ctx, msg, s.resourcesList)
	case "resources/read":
		mcp.Invoke(ctx, msg, s.resourcesRead)
	case "resources/subscribe":
		mcp.Invoke(ctx, msg, s.resourcesSubscribe)
	case "resources/unsubscribe":
		mcp.Invoke(ctx, msg, s.resourcesUnsubscribe)
	default:
		msg.SendError(ctx, mcp.ErrRPCMethodNotFound.WithMessage("%v", msg.Method))
	}
}

func (s *Server) initialize(ctx context.Context, msg mcp.Message, params mcp.InitializeRequest) (*mcp.InitializeResult, error) {
	if types.IsUISession(ctx) {
		// UI sessions get neither tools nor resources
		return &mcp.InitializeResult{
			ProtocolVersion: params.ProtocolVersion,
			ServerInfo: mcp.ServerInfo{
				Name:    version.Name,
				Version: version.Get().String(),
			},
		}, nil
	} else if !types.IsChatSession(ctx) {
		// Non-UI, non-chat sessions get tools but no resources
		return &mcp.InitializeResult{
			ProtocolVersion: params.ProtocolVersion,
			Capabilities: mcp.ServerCapabilities{
				Tools: &mcp.ToolsServerCapability{},
			},
			ServerInfo: mcp.ServerInfo{
				Name:    version.Name,
				Version: version.Get().String(),
			},
		}, nil
	}

	// Track this session for sending list_changed notifications
	sessionID, _ := types.GetSessionAndAccountID(ctx)

	// Ensure watcher is running for this session's directory
	if err := s.ensureFileWatcher(sessionID); err != nil {
		return nil, mcp.ErrRPCInternal.WithMessage("failed to start file watcher: %v", err)
	}
	s.subscriptions.AddSession(sessionID, msg.Session.Root())

	return &mcp.InitializeResult{
		ProtocolVersion: params.ProtocolVersion,
		Capabilities: mcp.ServerCapabilities{
			Tools: &mcp.ToolsServerCapability{},
			Resources: &mcp.ResourcesServerCapability{
				Subscribe:   true,
				ListChanged: true,
			},
		},
		ServerInfo: mcp.ServerInfo{
			Name:    version.Name,
			Version: version.Get().String(),
		},
	}, nil
}

// resourcesList returns all resources (todo + files).
func (s *Server) resourcesList(ctx context.Context, _ mcp.Message, _ mcp.ListResourcesRequest) (*mcp.ListResourcesResult, error) {
	resources := s.listTodoResources()

	// Add file resources
	fileResources, err := s.listFileResources(ctx)
	if err != nil {
		// Log but don't fail - still return todo resources
		slog.Error("failed to list file resources", "error", err)
	} else {
		resources = append(resources, fileResources...)
	}

	return &mcp.ListResourcesResult{Resources: resources}, nil
}

// resourcesRead reads a resource by URI (delegates to todo or file handlers).
func (s *Server) resourcesRead(ctx context.Context, msg mcp.Message, request mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
	if strings.HasPrefix(request.URI, "todo:///") {
		return s.readTodoResource(ctx, request.URI)
	} else if strings.HasPrefix(request.URI, "file:///") {
		return s.readFileResource(ctx, request.URI)
	}
	return nil, mcp.ErrRPCInvalidParams.WithMessage("unsupported resource URI: %s", request.URI)
}

// resourcesSubscribe subscribes to a resource by URI.
func (s *Server) resourcesSubscribe(ctx context.Context, msg mcp.Message, request mcp.SubscribeRequest) (*mcp.SubscribeResult, error) {
	sessionID, _ := types.GetSessionAndAccountID(ctx)

	// Delegate to specific handlers for validation
	var err error
	if strings.HasPrefix(request.URI, "todo:///") {
		err = s.subscribeTodoResource(request.URI)
	} else if strings.HasPrefix(request.URI, "file:///") {
		err = s.subscribeFileResource(ctx, request.URI)
	} else {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("unsupported resource URI: %s", request.URI)
	}
	if err != nil {
		return nil, err
	}

	// Add subscription to manager
	s.subscriptions.Subscribe(sessionID, msg.Session.Root(), request.URI)
	return &mcp.SubscribeResult{}, nil
}

// resourcesUnsubscribe unsubscribes from a resource.
func (s *Server) resourcesUnsubscribe(ctx context.Context, msg mcp.Message, request mcp.UnsubscribeRequest) (*mcp.UnsubscribeResult, error) {
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	s.subscriptions.Unsubscribe(sessionID, request.URI)
	return &mcp.UnsubscribeResult{}, nil
}

// Bash tool
type BashParams struct {
	Command     string  `json:"command"`
	Timeout     *int    `json:"timeout,omitempty"`
	Description *string `json:"description,omitempty"`
	Workdir     *string `json:"workdir,omitempty"`
}

func (s *Server) bash(ctx context.Context, params BashParams) (string, error) {
	if params.Command == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("command is required")
	}

	// Determine timeout
	timeout := defaultBashTimeout
	if params.Timeout != nil {
		timeout = max(time.Duration(*params.Timeout)*time.Millisecond, maxBashTimeout)
	}

	// Determine working directory
	workdir := "."
	if params.Workdir != nil {
		workdir = *params.Workdir
	} else {
		sessionID, _ := types.GetSessionAndAccountID(ctx)
		if sessionID != "" {
			dir, err := ensureSessionDir(sessionID)
			if err == nil {
				workdir = dir
			}
		}
		if workdir == "." {
			if cwd, err := os.Getwd(); err == nil {
				workdir = cwd
			}
		}
	}

	// Create context with timeout
	cmdCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// Execute command
	cmd := exec.CommandContext(cmdCtx, "bash", "-c", params.Command)
	cmd.Dir = workdir

	// Inject MCP_API_KEY from session environment if available
	if session := mcp.SessionFromContext(ctx); session != nil {
		if apiKey := session.GetEnvMap()["MCP_API_KEY"]; apiKey != "" {
			cmd.Env = append(os.Environ(), "MCP_API_KEY="+apiKey)
		}
	}

	output, err := cmd.CombinedOutput()

	// Check for timeout
	if cmdCtx.Err() == context.DeadlineExceeded {
		return "", mcp.ErrRPCInvalidParams.WithMessage("command timed out after %v", timeout)
	}

	// Check exit code
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return fmt.Sprintf("Exit code %d\n%s", exitErr.ExitCode(), output), nil
		}
		return "", fmt.Errorf("error executing command: %w", err)
	}

	if len(output) == 0 {
		return "Command completed successfully with no output.", nil
	}

	return string(output), nil
}

// Read tool
type ReadParams struct {
	// FilePath is the absolute path to the file to read.
	FilePath string `json:"file_path"`
	// Offset is the line number to start reading from (default beginning of file).
	// Only applicable to text files.
	Offset *int `json:"offset,omitempty"`
	// Limit is the number of lines to read (default 2000).
	// Only applicable to text files.
	Limit *int `json:"limit,omitempty"`
	// Pages is the page range for PDF files (e.g., "1-5", "3", "10-20").
	// Only applicable to PDF files. Maximum 10 pages per request.
	Pages *string `json:"pages,omitempty"`
}

func (s *Server) read(ctx context.Context, params ReadParams) (*mcp.CallToolResult, error) {
	if params.FilePath == "" {
		return nil, mcp.ErrRPCInvalidParams.WithMessage("file_path is required")
	}

	mimeType := mime.TypeByExtension(filepath.Ext(params.FilePath))

	if _, ok := types.PDFMimeTypes[mimeType]; ok {
		return readPDF(ctx, params)
	}
	if _, ok := types.ImageMimeTypes[mimeType]; ok {
		return readImage(params, mimeType)
	}

	return readText(params)
}

// Write tool
type WriteParams struct {
	FilePath string `json:"file_path"`
	Content  string `json:"content"`
}

func (s *Server) write(ctx context.Context, params WriteParams) (string, error) {
	if params.FilePath == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("file_path is required")
	}

	// Create parent directories if needed
	dir := filepath.Dir(params.FilePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", fmt.Errorf("error creating directories: %w", err)
	}

	// Write file
	if err := os.WriteFile(params.FilePath, []byte(params.Content), 0644); err != nil {
		return "", fmt.Errorf("error writing file: %w", err)
	}

	return fmt.Sprintf("Successfully wrote to file: %s", params.FilePath), nil
}

// Edit tool
type EditParams struct {
	FilePath   string `json:"file_path"`
	OldString  string `json:"old_string"`
	NewString  string `json:"new_string"`
	ReplaceAll bool   `json:"replace_all,omitempty"`
}

func (s *Server) edit(ctx context.Context, params EditParams) (string, error) {
	if params.FilePath == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("file_path is required")
	}
	if params.OldString == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("old_string is required")
	}
	if params.OldString == params.NewString {
		return "", mcp.ErrRPCInvalidParams.WithMessage("old_string and new_string must be different")
	}

	// Read file
	content, err := os.ReadFile(params.FilePath)
	if err != nil {
		return "", fmt.Errorf("error reading file: %w", err)
	}

	contentStr := string(content)

	// Check if old_string exists
	count := strings.Count(contentStr, params.OldString)
	if count == 0 {
		return "", mcp.ErrRPCInvalidParams.WithMessage("old_string not found in content")
	}

	// Check uniqueness if not replace_all
	if !params.ReplaceAll && count > 1 {
		return "", mcp.ErrRPCInvalidParams.WithMessage("old_string found multiple times and requires more code context to uniquely identify the intended match")
	}

	// Perform replacement
	var newContent string
	if params.ReplaceAll {
		newContent = strings.ReplaceAll(contentStr, params.OldString, params.NewString)
	} else {
		newContent = strings.Replace(contentStr, params.OldString, params.NewString, 1)
	}

	// Write back
	if err := os.WriteFile(params.FilePath, []byte(newContent), 0644); err != nil {
		return "", fmt.Errorf("error writing file: %w", err)
	}

	return fmt.Sprintf("Successfully edited file: %s", params.FilePath), nil
}

// Glob tool
type GlobParams struct {
	Pattern string  `json:"pattern"`
	Path    *string `json:"path,omitempty"`
}

func (s *Server) glob(ctx context.Context, params GlobParams) (string, error) {
	if params.Pattern == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("pattern is required")
	}

	searchPath := "."
	if params.Path != nil {
		searchPath = *params.Path
	}

	// Determine working directory (session directory by default)
	workdir := ""
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	if sessionID != "" {
		workdir = sessionDir(sessionID)
	}
	if workdir == "" {
		workdir, _ = os.Getwd()
		if workdir == "" {
			workdir = "."
		}
	}

	// Build ripgrep command
	args := []string{"--files", "--glob", params.Pattern}
	if params.Path != nil {
		args = append(args, searchPath)
	}

	cmd := exec.CommandContext(ctx, "rg", args...)
	cmd.Dir = workdir

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	// Run command (ignore exit code - rg returns non-zero when no matches)
	_ = cmd.Run()

	output := stdout.String()
	if output == "" {
		return "No files found matching pattern", nil
	}

	// Sort by modification time using xargs and ls
	// Use ls -t to sort by modification time
	lsCmd := exec.CommandContext(ctx, "bash", "-c", fmt.Sprintf("echo %q | xargs -r ls -t 2>/dev/null || true", output))
	lsCmd.Dir = workdir

	var lsOut bytes.Buffer
	lsCmd.Stdout = &lsOut

	if err := lsCmd.Run(); err == nil && lsOut.Len() > 0 {
		return lsOut.String(), nil
	}

	// Fallback to unsorted output
	return output, nil
}

// Grep tool
type GrepParams struct {
	Pattern    string  `json:"pattern"`
	Path       *string `json:"path,omitempty"`
	Glob       *string `json:"glob,omitempty"`
	OutputMode *string `json:"output_mode,omitempty"`
	B          *int    `json:"-B,omitempty"`
	A          *int    `json:"-A,omitempty"`
	C          *int    `json:"-C,omitempty"`
	N          *bool   `json:"-n,omitempty"`
	I          *bool   `json:"-i,omitempty"`
	Type       *string `json:"type,omitempty"`
	HeadLimit  *int    `json:"head_limit,omitempty"`
	Offset     *int    `json:"offset,omitempty"`
	Multiline  *bool   `json:"multiline,omitempty"`
}

type rgMatch struct {
	File  string
	Line  *int
	Text  *string
	Count int
}

func (s *Server) grep(ctx context.Context, params GrepParams) (string, error) {
	if params.Pattern == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("pattern is required")
	}

	outputMode := "files_with_matches"
	if params.OutputMode != nil {
		outputMode = *params.OutputMode
	}

	// Build ripgrep command
	args := []string{"--json", params.Pattern}

	// Add context flags (only for content mode)
	if outputMode == "content" {
		if params.C != nil {
			args = append(args, fmt.Sprintf("-C%d", *params.C))
		} else {
			if params.B != nil {
				args = append(args, fmt.Sprintf("-B%d", *params.B))
			}
			if params.A != nil {
				args = append(args, fmt.Sprintf("-A%d", *params.A))
			}
		}
	}

	// Case insensitive
	if params.I != nil && *params.I {
		args = append(args, "-i")
	}

	// Multiline
	if params.Multiline != nil && *params.Multiline {
		args = append(args, "-U", "--multiline-dotall")
	}

	// File type
	if params.Type != nil {
		args = append(args, "--type", *params.Type)
	}

	// Glob pattern
	if params.Glob != nil {
		args = append(args, "--glob", *params.Glob)
	}

	// Path
	if params.Path != nil {
		args = append(args, *params.Path)
	}

	// Determine working directory (session directory by default)
	workdir := ""
	sessionID, _ := types.GetSessionAndAccountID(ctx)
	if sessionID != "" {
		workdir = sessionDir(sessionID)
	}
	if workdir == "" {
		workdir, _ = os.Getwd()
		if workdir == "" {
			workdir = "."
		}
	}

	cmd := exec.CommandContext(ctx, "rg", args...)
	cmd.Dir = workdir

	var stdout bytes.Buffer
	cmd.Stdout = &stdout

	// Run command (ignore exit code)
	_ = cmd.Run()

	output := stdout.String()
	if output == "" {
		return "No matches found", nil
	}

	// Parse JSON output
	matches := []rgMatch{}
	currentFile := ""
	fileSet := make(map[string]bool)

	for line := range strings.SplitSeq(strings.TrimSpace(output), "\n") {
		var data map[string]any
		if err := json.Unmarshal([]byte(line), &data); err != nil {
			continue
		}

		msgType, _ := data["type"].(string)

		if msgType == "begin" {
			if pathData, ok := data["data"].(map[string]any); ok {
				if pathInfo, ok := pathData["path"].(map[string]any); ok {
					if text, ok := pathInfo["text"].(string); ok {
						currentFile = text
					}
				}
			}
		} else if msgType == "match" {
			matchData, _ := data["data"].(map[string]any)

			if outputMode == "content" {
				var lineNum int
				if ln, ok := matchData["line_number"].(float64); ok {
					lineNum = int(ln)
				}

				lineText := ""
				if linesData, ok := matchData["lines"].(map[string]any); ok {
					if text, ok := linesData["text"].(string); ok {
						lineText = text
					}
				}

				matches = append(matches, rgMatch{
					File: currentFile,
					Line: &lineNum,
					Text: &lineText,
				})
			} else if outputMode == "files_with_matches" {
				if !fileSet[currentFile] {
					matches = append(matches, rgMatch{File: currentFile})
					fileSet[currentFile] = true
				}
			} else if outputMode == "count" {
				// Track counts per file
				found := false
				for i := range matches {
					if matches[i].File == currentFile {
						matches[i].Count++
						found = true
						break
					}
				}
				if !found {
					matches = append(matches, rgMatch{File: currentFile, Count: 1})
				}
			}
		}
	}

	// Apply offset and limit
	var offset int
	if params.Offset != nil {
		offset = *params.Offset
	}

	if offset > 0 && offset < len(matches) {
		matches = matches[offset:]
	} else if offset >= len(matches) {
		return "No matches found", nil
	}

	if params.HeadLimit != nil && *params.HeadLimit > 0 && *params.HeadLimit < len(matches) {
		matches = matches[:*params.HeadLimit]
	}

	if len(matches) == 0 {
		return "No matches found", nil
	}

	// Format output
	var result strings.Builder
	showLineNumbers := true
	if params.N != nil {
		showLineNumbers = *params.N
	}

	for _, match := range matches {
		switch outputMode {
		case "content":
			if showLineNumbers && match.Line != nil {
				fmt.Fprintf(&result, "%s:%d:%s", match.File, *match.Line, *match.Text)
			} else {
				fmt.Fprintf(&result, "%s:%s", match.File, *match.Text)
			}
		case "files_with_matches":
			fmt.Fprintf(&result, "%s\n", match.File)
		case "count":
			fmt.Fprintf(&result, "%s:%d\n", match.File, match.Count)
		}
	}

	return strings.TrimSpace(result.String()), nil
}

// WebFetch tool
type WebFetchParams struct {
	URL     string `json:"url"`
	Format  string `json:"format"`
	Timeout *int   `json:"timeout,omitempty"`
}

func (s *Server) webFetch(ctx context.Context, params WebFetchParams) (string, error) {
	if params.URL == "" {
		return "", mcp.ErrRPCInvalidParams.WithMessage("url is required")
	}

	// Validate URL protocol
	if !strings.HasPrefix(params.URL, "http://") && !strings.HasPrefix(params.URL, "https://") {
		return "", mcp.ErrRPCInvalidParams.WithMessage("URL must start with http:// or https://")
	}

	// Determine timeout
	timeout := defaultHTTPTimeout
	if params.Timeout != nil {
		timeout = max(time.Duration(*params.Timeout)*time.Second, maxHTTPTimeout)
	}

	// Create HTTP client with timeout
	client := &http.Client{
		Timeout: timeout,
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, "GET", params.URL, nil)
	if err != nil {
		return "", fmt.Errorf("error creating request: %w", err)
	}

	// Set headers
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	switch params.Format {
	case "markdown":
		req.Header.Set("Accept", "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1")
	case "text":
		req.Header.Set("Accept", "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1")
	case "html":
		req.Header.Set("Accept", "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, text/markdown;q=0.7, */*;q=0.1")
	default:
		req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	}

	// Execute request
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("error fetching URL: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("failed to fetch URL: %d %s", resp.StatusCode, resp.Status)
	}

	// Check content length
	if resp.ContentLength > maxResponseSize {
		return "", mcp.ErrRPCInvalidParams.WithMessage("response too large (exceeds 5MB limit)")
	}

	// Read response body with size limit
	bodyBytes, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseSize+1))
	if err != nil {
		return "", fmt.Errorf("error reading response: %w", err)
	}

	if len(bodyBytes) > maxResponseSize {
		return "", mcp.ErrRPCInvalidParams.WithMessage("response too large (exceeds 5MB limit)")
	}

	content := string(bodyBytes)
	contentType := resp.Header.Get("Content-Type")

	// Process content based on format
	var processedContent string

	if params.Format == "markdown" && strings.Contains(contentType, "text/html") {
		// Convert HTML to Markdown
		markdown, err := htmltomarkdown.ConvertString(content)
		if err != nil {
			return "", fmt.Errorf("error converting HTML to markdown: %w", err)
		}
		processedContent = markdown
	} else if params.Format == "text" && strings.Contains(contentType, "text/html") {
		// Extract text from HTML
		processedContent = extractTextFromHTML(content)
	} else {
		processedContent = content
	}

	// Format output
	var result strings.Builder
	fmt.Fprintf(&result, "URL: %s\nContent-Type: %s\n\n", params.URL, contentType)
	result.WriteString(processedContent)

	return result.String(), nil
}

// Helper function to extract text from HTML
func extractTextFromHTML(htmlContent string) string {
	doc, err := html.Parse(strings.NewReader(htmlContent))
	if err != nil {
		return htmlContent
	}

	var buf strings.Builder
	var extract func(*html.Node)
	extract = func(n *html.Node) {
		if n.Type == html.TextNode {
			text := strings.TrimSpace(n.Data)
			if text != "" {
				buf.WriteString(text)
				buf.WriteString("\n")
			}
		}
		// Skip script, style, and other non-content elements
		if n.Type == html.ElementNode {
			switch n.Data {
			case "script", "style", "noscript", "iframe", "object", "embed":
				return
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			extract(c)
		}
	}

	extract(doc)
	return buf.String()
}
