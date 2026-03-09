package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/agents"
	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/llm"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
	"github.com/nanobot-ai/nanobot/pkg/sampling"
	"github.com/nanobot-ai/nanobot/pkg/servers/agent"
	"github.com/nanobot-ai/nanobot/pkg/servers/meta"
	"github.com/nanobot-ai/nanobot/pkg/servers/system"
	"github.com/nanobot-ai/nanobot/pkg/servers/workflows"
	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/nanobot-ai/nanobot/pkg/sessiondata"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type Runtime struct {
	*tools.Service
	llmConfig llm.Config
	opt       Options
}

type Options struct {
	Roots                     []mcp.Root
	Profiles                  []string
	MaxConcurrency            int
	CallbackHandler           mcp.CallbackHandler
	TokenStorage              mcp.TokenStorage
	OAuthRedirectURL          string
	DSN                       string
	TokenExchangeEndpoint     string
	TokenExchangeClientID     string
	TokenExchangeClientSecret string
	AuditLogCollector         *auditlogs.Collector
	ConfigDir                 string
}

func (o Options) Merge(other Options) (result Options) {
	result.MaxConcurrency = complete.Last(o.MaxConcurrency, other.MaxConcurrency)
	result.Profiles = append(o.Profiles, other.Profiles...)
	result.Roots = append(o.Roots, other.Roots...)
	result.CallbackHandler = complete.Last(o.CallbackHandler, other.CallbackHandler)
	result.OAuthRedirectURL = complete.Last(o.OAuthRedirectURL, other.OAuthRedirectURL)
	result.TokenStorage = complete.Last(o.TokenStorage, other.TokenStorage)
	result.DSN = complete.Last(o.DSN, other.DSN)
	result.TokenExchangeEndpoint = complete.Last(o.TokenExchangeEndpoint, other.TokenExchangeEndpoint)
	result.TokenExchangeClientID = complete.Last(o.TokenExchangeClientID, other.TokenExchangeClientID)
	result.TokenExchangeClientSecret = complete.Last(o.TokenExchangeClientSecret, other.TokenExchangeClientSecret)
	result.AuditLogCollector = complete.Last(o.AuditLogCollector, other.AuditLogCollector)
	result.ConfigDir = complete.Last(o.ConfigDir, other.ConfigDir)
	return
}

func NewRuntime(cfg llm.Config, opts ...Options) (*Runtime, error) {
	opt := complete.Complete(opts...)

	if opt.TokenStorage == nil && opt.DSN != "" {
		var err error
		opt.TokenStorage, err = session.NewStoreFromDSN(opt.DSN)
		if err != nil {
			return nil, fmt.Errorf("failed to create session store: %w", err)
		}
	}

	completer := llm.NewClient(cfg)
	registry := tools.NewToolsService(tools.Options{
		Roots:                     opt.Roots,
		Concurrency:               opt.MaxConcurrency,
		CallbackHandler:           opt.CallbackHandler,
		OAuthRedirectURL:          opt.OAuthRedirectURL,
		TokenStorage:              opt.TokenStorage,
		TokenExchangeEndpoint:     opt.TokenExchangeEndpoint,
		TokenExchangeClientID:     opt.TokenExchangeClientID,
		TokenExchangeClientSecret: opt.TokenExchangeClientSecret,
		AuditLogCollector:         opt.AuditLogCollector,
	})
	agentsService := agents.New(completer, registry)
	sampler := sampling.NewSampler(agentsService)

	// This is a circular dependency. Oh well, so much for good design.
	registry.SetSampler(sampler)

	r := &Runtime{
		Service:   registry,
		llmConfig: cfg,
		opt:       opt,
	}

	registry.AddServer("nanobot.meta", func(string) mcp.MessageHandler {
		return meta.NewServer(sessiondata.NewData(r))
	})

	registry.AddServer("nanobot.agent", func(name string) mcp.MessageHandler {
		return agent.NewServer(sessiondata.NewData(r), r, agentsService, name)
	})

	registry.AddServer("nanobot.system", func(string) mcp.MessageHandler {
		return system.NewServer(opt.ConfigDir)
	})

	registry.AddServer("nanobot.workflows", func(string) mcp.MessageHandler {
		return workflows.NewServer()
	})

	registry.AddServer("nanobot.workflow-tools", func(string) mcp.MessageHandler {
		return workflows.NewToolsServer()
	})

	return r, nil
}

func (r *Runtime) WithTempSession(ctx context.Context, config *types.Config) context.Context {
	session := mcp.NewEmptySession(ctx)
	session.Set(types.ConfigSessionKey, config)
	return mcp.WithSession(types.WithConfig(ctx, *config), session)
}

func (r *Runtime) getToolFromRef(ctx context.Context, config types.Config, serverRef string) (*tools.ListToolsResult, error) {
	var (
		server, tool string
	)

	toolRef := strings.Split(serverRef, "/")
	if len(toolRef) == 1 {
		_, ok := config.Agents[toolRef[0]]
		if ok {
			server, tool = toolRef[0], toolRef[0]
		} else {
			server, tool = "", toolRef[0]
		}
	} else if len(toolRef) == 2 {
		server, tool = toolRef[0], toolRef[1]
	} else {
		return nil, fmt.Errorf("invalid tool reference: %s", serverRef)
	}

	toolList, err := r.ListTools(ctx, tools.ListToolsOptions{
		Servers: []string{server},
		Tools:   []string{tool},
	})
	if err != nil {
		return nil, err
	}

	if len(toolList) != 1 || len(toolList[0].Tools) != 1 {
		return nil, fmt.Errorf("found %d tools with name %s on server %s", len(toolList), tool, server)
	}

	return &tools.ListToolsResult{
		Server: toolList[0].Server,
		Tools:  []mcp.Tool{toolList[0].Tools[0]},
	}, nil
}

func (r *Runtime) CallFromCLI(ctx context.Context, serverRef string, args ...string) (*mcp.CallToolResult, error) {
	var (
		argValue any
		argMap   = map[string]string{}
		config   = types.ConfigFromContext(ctx)
	)

	tools, err := r.getToolFromRef(ctx, config, serverRef)
	if err != nil {
		return nil, err
	}

	if bytes.Equal(tools.Tools[0].InputSchema, types.ChatInputSchema) {
		argValue = types.SampleCallRequest{
			Prompt: strings.Join(args, " "),
		}
		args = nil
	}

	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "--") {
			if len(args) > 1 {
				return nil, fmt.Errorf("if using JSON syntax you must pass one argument: got %d", len(args))
			}
			err := json.Unmarshal([]byte(arg), &argValue)
			if err != nil {
				return nil, fmt.Errorf("failed to unmarshal JSON: %w", err)
			}
			break
		}
		k, v, ok := strings.Cut(arg, "=")
		if !ok {
			if i+1 >= len(args) {
				return nil, fmt.Errorf("missing value for argument %q", arg)
			}
			v = args[i+1]
			i++
		}
		argMap[strings.TrimPrefix(k, "--")] = v
		argValue = argMap
	}

	if argValue == nil {
		argValue = map[string]any{}
	}

	callResult, err := r.Call(ctx, tools.Server, tools.Tools[0].Name, argValue)
	if err != nil {
		return nil, err
	}
	return &mcp.CallToolResult{
		StructuredContent: callResult.StructuredContent,
		IsError:           callResult.IsError,
		Content:           callResult.Content,
	}, nil
}
