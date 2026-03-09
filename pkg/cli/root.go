package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/api"
	"github.com/nanobot-ai/nanobot/pkg/auth"
	"github.com/nanobot-ai/nanobot/pkg/cmd"
	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/config"
	"github.com/nanobot-ai/nanobot/pkg/llm"
	"github.com/nanobot-ai/nanobot/pkg/llm/anthropic"
	"github.com/nanobot-ai/nanobot/pkg/llm/responses"
	"github.com/nanobot-ai/nanobot/pkg/log"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
	"github.com/nanobot-ai/nanobot/pkg/runtime"
	"github.com/nanobot-ai/nanobot/pkg/server"
	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/version"
	"github.com/spf13/cobra"
	"sigs.k8s.io/yaml"
)

func New() *cobra.Command {
	n := &Nanobot{}

	root := cmd.Command(n,
		NewCall(n),
		NewTargets(n),
		NewSessions(n),
		NewRun(n))
	return root
}

type Nanobot struct {
	Debug                   bool              `usage:"Enable debug logging"`
	Trace                   bool              `usage:"Enable trace logging"`
	Env                     []string          `usage:"Environment variables to set in the form of KEY=VALUE, or KEY to load from current environ" short:"e"`
	EnvFile                 string            `usage:"Path to the environment file (default: ./nanobot.env)" default:"./nanobot.env"`
	EmptyEnv                bool              `usage:"Do not load environment variables from the environment by default"`
	DefaultModel            string            `usage:"Default model to use for completions" default:"gpt-4.1" env:"NANOBOT_DEFAULT_MODEL" name:"default-model"`
	DefaultMiniModel        string            `usage:"Default model to use for things like thread summaries" default:"gpt-4.1" env:"NANOBOT_DEFAULT_MINI_MODEL" name:"default-mini-model"`
	OpenAIAPIKey            string            `usage:"OpenAI API key" env:"OPENAI_API_KEY" name:"openai-api-key"`
	OpenAIBaseURL           string            `usage:"OpenAI API URL" env:"OPENAI_BASE_URL" name:"openai-base-url"`
	OpenAIHeaders           map[string]string `usage:"OpenAI API headers" env:"OPENAI_HEADERS" name:"openai-headers"`
	OpenAIChatCompletionAPI bool              `usage:"Use OpenAI Chat Completion API instead of the newer Responses API" env:"OPENAI_CHAT_COMPLETION_API" name:"openai-chat-completion-api"`
	AnthropicAPIKey         string            `usage:"Anthropic API key" env:"ANTHROPIC_API_KEY" name:"anthropic-api-key"`
	AnthropicBaseURL        string            `usage:"Anthropic API URL" env:"ANTHROPIC_BASE_URL" name:"anthropic-base-url"`
	AnthropicHeaders        map[string]string `usage:"Anthropic API headers" env:"ANTHROPIC_HEADERS" name:"anthropic-headers"`
	MaxConcurrency          int               `usage:"The maximum number of concurrent tasks in a parallel loop" default:"10" hidden:"true"`
	Chdir                   string            `usage:"Change directory to this path before running the nanobot" default:"." short:"C"`
	State                   string            `usage:"Path to the state file" default:"./nanobot.db"`
	ConfigPath              string            `usage:"Path to nanobot configuration file or directory" default:".nanobot/" name:"config" short:"c"`
	ExcludeBuiltInAgents    bool              `usage:"Exclude built-in agents from the configuration"`
}

func ensureDirectoryForDSN(dsn string) error {
	dsnFile, _, _ := strings.Cut(dsn, "?")
	dsnFile = strings.TrimPrefix(dsnFile, "file:")
	if !strings.HasSuffix(dsnFile, ".db") {
		return nil
	}

	dir := filepath.Dir(dsnFile)
	if dir == "." {
		return nil
	}

	_, err := os.Stat(dir)
	if !errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	return os.MkdirAll(dir, 0o700)
}

func (n *Nanobot) DSN() string {
	dsn := os.Expand(n.State, func(s string) string {
		if s == "XDG_CONFIG_HOME" {
			userConfigDir, err := os.UserConfigDir()
			if err != nil {
				slog.Error("Failed to get user config directory", "error", err)
				os.Exit(1)
			}
			return userConfigDir
		}
		return os.Getenv(s)
	})

	if err := ensureDirectoryForDSN(dsn); err != nil {
		slog.Error("Failed to ensure directory for state file", "dsn", dsn, "error", err)
		os.Exit(1)
	}

	return dsn
}

func (n *Nanobot) Customize(cmd *cobra.Command) {
	cmd.Short = "Nanobot: Build MCP Agents"
	cmd.CompletionOptions.HiddenDefaultCmd = true
	cmd.Version = version.Get().String()
}

func (n *Nanobot) PersistentPre(cmd *cobra.Command, _ []string) error {
	if n.Chdir != "." {
		if err := os.Chdir(n.Chdir); err != nil {
			return fmt.Errorf("failed to change directory to %s: %w", n.Chdir, err)
		}
	}

	if n.Trace {
		log.EnableProgress = true
	}

	log.ConfigureSlog(n.Debug, n.Trace)
	log.EnableMessages = log.EnableMessages || n.Debug || n.Trace

	for _, sub := range cmd.Commands() {
		if sub.Name() == "help" {
			sub.Hidden = true
			sub.Use = " help"
		}
	}
	return nil
}

func display(obj any, format string) bool {
	switch format {
	case "json":
		data, _ := json.MarshalIndent(obj, "", "  ")
		fmt.Println(string(data))
		return true
	case "yaml":
		data, _ := yaml.Marshal(obj)
		fmt.Println(string(data))
		return true
	}
	return false
}

func (n *Nanobot) llmConfig() llm.Config {
	return llm.Config{
		DefaultModel:     n.DefaultModel,
		DefaultMiniModel: n.DefaultMiniModel,
		Responses: responses.Config{
			APIKey:            n.OpenAIAPIKey,
			BaseURL:           n.OpenAIBaseURL,
			Headers:           n.OpenAIHeaders,
			ChatCompletionAPI: n.OpenAIChatCompletionAPI,
		},
		Anthropic: anthropic.Config{
			APIKey:  n.AnthropicAPIKey,
			BaseURL: n.AnthropicBaseURL,
			Headers: n.AnthropicHeaders,
		},
	}
}

func (n *Nanobot) loadEnv() (map[string]string, error) {
	env := map[string]string{}
	cwd, err := os.Getwd()
	if err == nil {
		env["PWD"] = cwd
		env["CWD"] = cwd
	}

	if !n.EmptyEnv {
		for _, kv := range os.Environ() {
			k, v, _ := strings.Cut(kv, "=")
			env[k] = v
		}
	}

	data, err := os.ReadFile(n.EnvFile)
	if errors.Is(err, fs.ErrNotExist) {
		if n.EnvFile != "./nanobot.env" {
			return nil, err
		}
	} else {
		for line := range strings.SplitSeq(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			k, v, _ := strings.Cut(line, "=")
			env[k] = v
		}
	}

	if _, ok := env["NANOBOT_MCP"]; !ok {
		env["NANOBOT_MCP"] = "true"
	}

	for _, kv := range n.Env {
		k, v, ok := strings.Cut(kv, "=")
		if !ok {
			v = os.Getenv(k)
		}
		env[k] = v
	}

	return env, nil
}

func (n *Nanobot) ReadConfig(ctx context.Context, cfgPath string, includeDefaultAgents bool, opts ...runtime.Options) (*types.Config, error) {
	cfg, _, err := config.Load(ctx, cfgPath, includeDefaultAgents, complete.Complete(opts...).Profiles...)
	return cfg, err
}

func (n *Nanobot) GetRuntime(opts ...runtime.Options) (*runtime.Runtime, error) {
	return runtime.NewRuntime(n.llmConfig(), opts...)
}

func (n *Nanobot) Run(cmd *cobra.Command, _ []string) error {
	return cmd.Help()
}

type mcpOpts struct {
	Auth               auth.Auth
	ListenAddress      string
	HealthzPath        string
	ForceFetchToolList bool
	StartUI            bool
}

func (n *Nanobot) runMCP(ctx context.Context, baseConfig types.ConfigFactory, runt *runtime.Runtime, oauthCallbackHandler mcp.CallbackServer, auditLogCollector *auditlogs.Collector, opts mcpOpts) error {
	envProvider := func() (map[string]string, error) {
		return n.loadEnv()
	}

	env, err := envProvider()
	if err != nil {
		return fmt.Errorf("failed to load environment: %w", err)
	}

	config := func(ctx context.Context, profile string) (types.Config, error) {
		cfg, err := baseConfig(ctx, profile)
		if err != nil {
			return types.Config{}, err
		}

		if opts.StartUI {
			return config.Merge(cfg, config.UI)
		}

		return cfg, nil
	}

	address := opts.ListenAddress
	if strings.HasPrefix("address", "http://") {
		address = strings.TrimPrefix(address, "http://")
	} else if strings.HasPrefix(address, "https://") {
		return fmt.Errorf("https:// is not supported, use http:// instead")
	}

	sessionManager, err := session.NewManager(n.DSN())
	if err != nil {
		return err
	}

	var mcpServer mcp.MessageHandler = server.NewServer(runt, config, sessionManager, server.Options{
		ForceFetchToolList: opts.ForceFetchToolList,
	})

	if address == "stdio" {
		stdio := mcp.NewStdioServer(envProvider, mcpServer)
		if err := stdio.Start(ctx, os.Stdin, os.Stdout); err != nil {
			return fmt.Errorf("failed to start stdio server: %w", err)
		}

		stdio.Wait()
		return nil
	}

	httpServer, err := mcp.NewHTTPServer(ctx, envProvider, mcpServer, mcp.HTTPServerOptions{
		HealthCheckPath:   opts.HealthzPath,
		RunHealthChecker:  opts.HealthzPath != "" && os.Getenv("NANOBOT_DISABLE_HEALTH_CHECKER") != "true",
		SessionStore:      sessionManager,
		AuditLogCollector: auditLogCollector,
	})
	if err != nil {
		return fmt.Errorf("failed to create HTTP server: %w", err)
	}

	mux := http.NewServeMux()
	if oauthCallbackHandler != nil {
		mux.Handle("/oauth/callback", oauthCallbackHandler)
	}
	if opts.StartUI {
		mux.Handle("/", session.UISession(httpServer, sessionManager, api.Handler(sessionManager, address)))
	} else {
		mux.Handle("/", httpServer)
	}

	handler, err := auth.Wrap(ctx, env, opts.Auth, n.DSN(), opts.HealthzPath, mux)
	if err != nil {
		return fmt.Errorf("failed to setup auth: %w", err)
	}

	s := &http.Server{
		Addr:    address,
		Handler: api.Cors(handler),
	}

	context.AfterFunc(ctx, func() {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = s.Shutdown(ctx)
	})

	slog.Info("Starting server", "url", "http://"+address)
	err = s.ListenAndServe()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	slog.Debug("Server stopped", "error", err)
	return err
}
