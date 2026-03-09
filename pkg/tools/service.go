package tools

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"net/http"
	"net/url"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/envvar"
	"github.com/nanobot-ai/nanobot/pkg/expr"
	"github.com/nanobot-ai/nanobot/pkg/fileuri"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
	"github.com/nanobot-ai/nanobot/pkg/sampling"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

type Service struct {
	roots                     []mcp.Root
	sampler                   Sampler
	runner                    mcp.Runner
	callbackHandler           mcp.CallbackHandler
	oauthRedirectURL          string
	tokenStorage              mcp.TokenStorage
	concurrency               int
	serverFactories           map[string]func(name string) mcp.MessageHandler
	tokenExchangeEndpoint     string
	tokenExchangeClientID     string
	tokenExchangeClientSecret string
	auditLogCollector         *auditlogs.Collector
}

type Sampler interface {
	Sample(ctx context.Context, sampling mcp.CreateMessageRequest, opts ...sampling.SamplerOptions) (*types.CallResult, error)
}

type Options struct {
	Roots                     []mcp.Root
	Concurrency               int
	CallbackHandler           mcp.CallbackHandler
	OAuthRedirectURL          string
	TokenStorage              mcp.TokenStorage
	TokenExchangeEndpoint     string
	TokenExchangeClientID     string
	TokenExchangeClientSecret string
	AuditLogCollector         *auditlogs.Collector
}

func (r Options) Merge(other Options) (result Options) {
	result.Roots = append(r.Roots, other.Roots...)
	result.Concurrency = complete.Last(r.Concurrency, other.Concurrency)
	result.CallbackHandler = complete.Last(r.CallbackHandler, other.CallbackHandler)
	result.OAuthRedirectURL = complete.Last(r.OAuthRedirectURL, other.OAuthRedirectURL)
	result.TokenStorage = complete.Last(r.TokenStorage, other.TokenStorage)
	result.TokenExchangeEndpoint = complete.Last(r.TokenExchangeEndpoint, other.TokenExchangeEndpoint)
	result.TokenExchangeClientID = complete.Last(r.TokenExchangeClientID, other.TokenExchangeClientID)
	result.TokenExchangeClientSecret = complete.Last(r.TokenExchangeClientSecret, other.TokenExchangeClientSecret)
	result.AuditLogCollector = complete.Last(r.AuditLogCollector, other.AuditLogCollector)
	return result
}

func (r Options) Complete() Options {
	if r.Concurrency == 0 {
		r.Concurrency = 10
	}
	return r
}

func NewToolsService(opts ...Options) *Service {
	opt := complete.Complete(opts...)
	return &Service{
		roots:                     opt.Roots,
		concurrency:               opt.Concurrency,
		oauthRedirectURL:          opt.OAuthRedirectURL,
		callbackHandler:           opt.CallbackHandler,
		tokenStorage:              opt.TokenStorage,
		tokenExchangeEndpoint:     opt.TokenExchangeEndpoint,
		tokenExchangeClientID:     opt.TokenExchangeClientID,
		tokenExchangeClientSecret: opt.TokenExchangeClientSecret,
		auditLogCollector:         opt.AuditLogCollector,
	}
}

func (s *Service) GetAgentAttributes(_ context.Context, name string) (agentConfigName string, agentAttribute map[string]any, _ error) {
	// noop
	return name, nil, nil
}

func (s *Service) AddServer(name string, factory func(name string) mcp.MessageHandler) {
	if s.serverFactories == nil {
		s.serverFactories = make(map[string]func(string) mcp.MessageHandler)
	}
	s.serverFactories[name] = factory
}

func (s *Service) SetSampler(sampler Sampler) {
	s.sampler = sampler
}

// buildAuditLog creates a new audit log entry for internal service calls
func buildAuditLog(msg *mcp.Message, session *mcp.Session) *auditlogs.MCPAuditLog {
	auditLog := &auditlogs.MCPAuditLog{
		CreatedAt:     time.Now(),
		CallType:      msg.Method,
		SessionID:     session.ID(),
		ClientName:    session.InitializeRequest.ClientInfo.Name,
		ClientVersion: session.InitializeRequest.ClientInfo.Version,
	}
	auditLog.RequestBody, _ = json.Marshal(msg)

	session.Get("subject", &auditLog.Subject)
	session.Get("clientIP", &auditLog.ClientIP)
	session.Get("apiKey", &auditLog.APIKey)

	return auditLog
}

// collectAuditLog finalizes and collects the audit log entry
func (s *Service) collectAuditLog(auditLog *auditlogs.MCPAuditLog) {
	if s.auditLogCollector == nil || auditLog == nil {
		return
	}

	auditLog.ProcessingTimeMs = time.Since(auditLog.CreatedAt).Milliseconds()
	if auditLog.ResponseStatus == 0 {
		if auditLog.Error != "" {
			auditLog.ResponseStatus = http.StatusInternalServerError
		} else {
			auditLog.ResponseStatus = http.StatusOK
		}
	}
	s.auditLogCollector.CollectMCPAuditEntry(*auditLog)
}

func (s *Service) GetDynamicInstruction(ctx context.Context, instruction types.DynamicInstructions) (string, error) {
	if !instruction.IsSet() {
		return "", nil
	}

	session := mcp.SessionFromContext(ctx)

	if !instruction.IsPrompt() {
		return expr.EvalString(ctx, session.GetEnvMap(), s.newGlobals(ctx, nil), instruction.Instructions)
	}

	prompt, err := s.GetPrompt(ctx, instruction.MCPServer, instruction.Prompt, envvar.ReplaceMap(session.GetEnvMap(), instruction.Args))
	if err != nil {
		return "", fmt.Errorf("failed to get prompt: %w", err)
	}
	if len(prompt.Messages) != 1 {
		return "", fmt.Errorf("prompt %s/%s returned %d messages, expected 1",
			instruction.MCPServer, instruction.Prompt, len(prompt.Messages))
	}
	return prompt.Messages[0].Content.Text, nil
}

func (s *Service) GetPrompt(ctx context.Context, target, prompt string, args map[string]string) (*mcp.GetPromptResult, error) {
	if target == "" && prompt != "" {
		target = prompt
	}

	config := types.ConfigFromContext(ctx)

	if inline, ok := config.Prompts[target]; ok && target == prompt {
		vals := map[string]any{}
		for k, v := range args {
			vals[k] = v
		}
		rendered, err := expr.EvalString(ctx, mcp.SessionFromContext(ctx).GetEnvMap(), s.newGlobals(ctx, vals), inline.Template)
		if err != nil {
			return nil, fmt.Errorf("failed to render inline prompt %s: %w", prompt, err)
		}
		return &mcp.GetPromptResult{
			Messages: []mcp.PromptMessage{
				{
					Role: "user",
					Content: mcp.Content{
						Type: "text",
						Text: rendered,
					},
				},
			},
		}, nil
	}

	c, err := s.GetClient(ctx, target)
	if err != nil {
		return nil, err
	}

	return c.GetPrompt(ctx, prompt, args)
}

type clientFactory struct {
	clientLock *sync.Mutex
	client     *mcp.Client
	oldState   *mcp.SessionState
	envHash    string
	new        func(client *mcp.SessionState) (*mcp.Client, error)
}

func newClientFactory(f func(state *mcp.SessionState) (*mcp.Client, error)) clientFactory {
	return clientFactory{
		clientLock: &sync.Mutex{},
		new:        f,
	}
}

func (c *clientFactory) get(envHash string) (*mcp.Client, error) {
	c.clientLock.Lock()
	defer c.clientLock.Unlock()

	if c.client != nil && c.envHash == envHash {
		return c.client, nil
	}

	if c.client != nil {
		c.client.Close(false)
		c.client = nil
	}

	newClient, err := c.new(c.oldState)
	if err != nil {
		return nil, err
	}
	c.client = newClient
	c.envHash = envHash
	return c.client, nil
}

func (c *clientFactory) Close(deleteSession bool) {
	c.clientLock.Lock()
	defer c.clientLock.Unlock()
	if c.client != nil {
		c.client.Close(deleteSession)
		c.client = nil
	}
	c.envHash = ""
}

func (c *clientFactory) Serialize() (any, error) {
	if c.client == nil || c.client.Session.ID() == "" {
		return nil, nil
	}
	return c.client.Session.State()
}

func (c *clientFactory) Deserialize(data any) (_ any, err error) {
	if data == nil {
		return &clientFactory{
			clientLock: &sync.Mutex{},
			envHash:    c.envHash,
			new:        c.new,
		}, nil
	}

	var (
		state mcp.SessionState
	)
	if err := mcp.JSONCoerce(data, &state); err != nil {
		return nil, fmt.Errorf("failed to coerce session state data: %w", err)
	}

	return &clientFactory{
		clientLock: &sync.Mutex{},
		oldState:   &state,
		envHash:    c.envHash,
		new:        c.new,
	}, nil
}

func (s *Service) GetClient(ctx context.Context, name string) (*mcp.Client, error) {
	session := mcp.SessionFromContext(ctx).Root()
	if session == nil {
		return nil, fmt.Errorf("session not found in context")
	}

	envHash, err := envMapHash(session.GetEnvMap())
	if err != nil {
		return nil, fmt.Errorf("failed to hash env map: %w", err)
	}

	sessionKey := "clients/" + name
	factory := newClientFactory(func(state *mcp.SessionState) (*mcp.Client, error) {
		return s.newClient(ctx, name, state)
	})
	if session.Get(sessionKey, &factory) {
		return factory.get(envHash)
	}

	// ensure we are holding the same object
	session.Set(sessionKey, &factory)
	session.Get(sessionKey, &factory)

	return factory.get(envHash)
}

func envMapHash(env map[string]string) (string, error) {
	digest := sha256.New()
	if err := json.NewEncoder(digest).Encode(env); err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", digest.Sum(nil)), nil
}

func (s *Service) newClient(ctx context.Context, name string, state *mcp.SessionState) (*mcp.Client, error) {
	session := mcp.SessionFromContext(ctx).Root()
	if session == nil {
		return nil, fmt.Errorf("session not found in context")
	}

	if session.HookRunner == nil {
		session.HookRunner = s
	}

	config := types.ConfigFromContext(ctx)

	var (
		wire          mcp.Wire
		mcpConfig     mcp.Server
		ok            bool
		serverFactory func(string) mcp.MessageHandler
	)

	serverFactory, ok = s.serverFactories[name]
	if !ok {
		mcpConfig, ok = config.MCPServers[name]
	}
	if !ok {
		_, ok = config.Agents[name]
		if ok {
			serverFactory, ok = s.serverFactories["nanobot.agent"]
		}
	}
	if !ok {
		return nil, fmt.Errorf("MCP server %s not found in config", name)
	}

	if serverFactory != nil {
		serverSession, err := mcp.NewExistingServerSession(session.Context(), mcp.SessionState{}, serverFactory(name))
		if err != nil {
			return nil, fmt.Errorf("failed to create meta server session: %w", err)
		}
		wire = serverSession
	}

	roots := func(ctx context.Context) ([]mcp.Root, error) {
		var roots mcp.ListRootsResult
		if session.InitializeRequest.Capabilities.Roots != nil {
			err := session.Exchange(ctx, "roots/list", mcp.ListRootsRequest{}, &roots)
			if err != nil {
				return nil, fmt.Errorf("failed to list roots: %w", err)
			}
		}

		roots.Roots = append(roots.Roots, s.roots...)

		return roots.Roots, nil
	}

	var oauthRedirectURL string
	if session.Get(types.PublicURLSessionKey, &oauthRedirectURL) {
		u, err := url.Parse(oauthRedirectURL)
		if err == nil {
			oauthRedirectURL = u.Scheme + "://" + u.Host
		}
		oauthRedirectURL = strings.TrimSuffix(oauthRedirectURL, "/") + "/oauth/callback"
	} else {
		oauthRedirectURL = s.oauthRedirectURL
	}

	clientOpts := mcp.ClientOption{
		Roots:         roots,
		Env:           session.GetEnvMap(),
		ParentSession: session,
		OnRoots: func(ctx context.Context, msg mcp.Message) (err error) {
			auditLog := buildAuditLog(&msg, session)
			defer func() {
				if err != nil {
					auditLog.Error = err.Error()
					if auditLog.ResponseStatus < http.StatusBadRequest {
						auditLog.ResponseStatus = http.StatusInternalServerError
						if errors.Is(err, mcp.ErrNoReader) {
							auditLog.ResponseStatus = http.StatusNotFound
						}
					}
				}
				s.collectAuditLog(auditLog)
			}()

			roots, err := roots(mcp.WithMCPServerConfig(mcp.WithAuditLog(ctx, auditLog), mcpConfig))
			if err != nil {
				return fmt.Errorf("failed to get roots: %w", err)
			}

			result := mcp.ListRootsResult{Roots: roots}
			auditLog.ResponseBody, _ = json.Marshal(result)
			return msg.Reply(ctx, result)
		},
		OnNotify: func(ctx context.Context, msg mcp.Message) (err error) {
			auditLog := buildAuditLog(&msg, session)
			defer func() {
				if err != nil {
					auditLog.Error = err.Error()
					if auditLog.ResponseStatus < http.StatusBadRequest {
						auditLog.ResponseStatus = http.StatusInternalServerError
						if errors.Is(err, mcp.ErrNoReader) {
							auditLog.ResponseStatus = http.StatusNotFound
						}
					}
				}
				s.collectAuditLog(auditLog)
			}()

			return session.Send(mcp.WithMCPServerConfig(mcp.WithAuditLog(ctx, auditLog), mcpConfig), msg)
		},
		OnLogging: func(ctx context.Context, logMsg mcp.LoggingMessage) (err error) {
			data, err := json.Marshal(mcp.LoggingMessage{
				Level:  logMsg.Level,
				Logger: logMsg.Logger,
				Data: map[string]any{
					"server": name,
					"data":   logMsg.Data,
				},
			})
			if err != nil {
				return fmt.Errorf("failed to marshal logging message: %w", err)
			}

			msg := mcp.Message{
				JSONRPC: "2.0",
				Method:  "notifications/message",
				Params:  data,
			}

			auditLog := buildAuditLog(&msg, session)
			defer func() {
				if err != nil {
					auditLog.Error = err.Error()
					if auditLog.ResponseStatus < http.StatusBadRequest {
						auditLog.ResponseStatus = http.StatusInternalServerError
						if errors.Is(err, mcp.ErrNoReader) {
							auditLog.ResponseStatus = http.StatusNotFound
						}
					}
				}
				s.collectAuditLog(auditLog)
			}()

			return session.Send(mcp.WithMCPServerConfig(mcp.WithAuditLog(ctx, auditLog), mcpConfig), msg)
		},
		Runner: &s.runner,
		HTTPClientOptions: mcp.HTTPClientOptions{
			OAuthRedirectURL:          oauthRedirectURL,
			CallbackHandler:           s.callbackHandler,
			TokenStorage:              s.tokenStorage,
			TokenExchangeEndpoint:     s.tokenExchangeEndpoint,
			TokenExchangeClientID:     s.tokenExchangeClientID,
			TokenExchangeClientSecret: s.tokenExchangeClientSecret,
		},
		Wire:         wire,
		SessionState: state,
		HookRunner:   s,
	}

	if session.InitializeRequest.Capabilities.Elicitation == nil {
		clientOpts.OnElicit = func(ctx context.Context, _ mcp.Message, elicitation mcp.ElicitRequest) (result mcp.ElicitResult, _ error) {
			return mcp.ElicitResult{
				Action: "cancel",
			}, nil
		}
	} else {
		clientOpts.OnElicit = func(ctx context.Context, msg mcp.Message, elicitation mcp.ElicitRequest) (result mcp.ElicitResult, err error) {
			auditLog := buildAuditLog(&msg, session)
			defer func() {
				if err != nil {
					auditLog.Error = err.Error()
					if auditLog.ResponseStatus < http.StatusBadRequest {
						auditLog.ResponseStatus = http.StatusInternalServerError
						if errors.Is(err, mcp.ErrNoReader) {
							auditLog.ResponseStatus = http.StatusNotFound
						}
					}
				}
				s.collectAuditLog(auditLog)
			}()

			if err = session.Exchange(mcp.WithMCPServerConfig(mcp.WithAuditLog(ctx, auditLog), mcpConfig), "elicitation/create", elicitation, &result); err != nil {
				auditLog.Error = err.Error()
			} else {
				auditLog.ResponseBody, _ = json.Marshal(result)
			}
			return result, err
		}
	}
	if s.sampler != nil {
		clientOpts.OnSampling = func(ctx context.Context, samplingRequest mcp.CreateMessageRequest) (mcp.CreateMessageResult, error) {
			msg, err := mcp.NewMessageWithID("sampling/createMessage", samplingRequest)
			if err != nil {
				return mcp.CreateMessageResult{}, fmt.Errorf("failed to create message: %w", err)
			}
			includeContext := samplingRequest.IncludeContext
			if includeContext == "" {
				includeContext = "none"
			}
			result, err := s.sampler.Sample(ctx, samplingRequest, sampling.SamplerOptions{
				ToolChoice:         samplingRequest.ToolChoice,
				ToolIncludeContext: includeContext,
				ToolSource:         name,
				Tools:              samplingRequest.Tools,
				ProgressToken:      uuid.String(),
				Chat:               new(bool),
			})
			if err != nil {
				if errors.Is(err, sampling.ErrNoMatchingModel) && session.InitializeRequest.Capabilities.Sampling != nil {
					auditLog := buildAuditLog(msg, session)
					defer func() {
						if err != nil {
							auditLog.Error = err.Error()
							if auditLog.ResponseStatus < http.StatusBadRequest {
								auditLog.ResponseStatus = http.StatusInternalServerError
								if errors.Is(err, mcp.ErrNoReader) {
									auditLog.ResponseStatus = http.StatusNotFound
								}
							}
						}
						s.collectAuditLog(auditLog)
					}()

					// There was no matching model, but the session supports sampling. Send the sampling request to it.
					var result mcp.CreateMessageResult
					if err = session.Exchange(mcp.WithMCPServerConfig(mcp.WithAuditLog(ctx, auditLog), mcpConfig), "sampling/createMessage", samplingRequest, &result); err != nil {
						return result, fmt.Errorf("failed to send sampling request: %w", err)
					}
					auditLog.ResponseBody, _ = json.Marshal(result)
					return result, nil
				}

				return mcp.CreateMessageResult{}, err
			}
			return mcp.CreateMessageResult{
				Content:    result.Content,
				Role:       "assistant",
				Model:      result.Model,
				StopReason: result.StopReason,
			}, nil
		}
	}

	sessionCtx := session.Context()
	token := mcp.TokenFromContext(ctx)
	if token != "" {
		sessionCtx = mcp.WithToken(sessionCtx, token)
	}
	sessionCtx = mcp.WithAuditLog(sessionCtx, mcp.AuditLogFromContext(ctx))

	return mcp.NewClient(sessionCtx, name, mcpConfig, clientOpts)
}

func (s *Service) sampleCall(ctx context.Context, agent string, args any, opts ...SampleCallOptions) (*types.CallResult, error) {
	config := types.ConfigFromContext(ctx)
	createMessageRequest, err := s.convertToSampleRequest(config, agent, args)
	if err != nil {
		return nil, err
	}

	opt := complete.Complete(opts...)

	return s.sampler.Sample(ctx, *createMessageRequest, sampling.SamplerOptions{
		ProgressToken: opt.ProgressToken,
	})
}

type CallOptions struct {
	ProgressToken      any
	LogData            map[string]any
	ReturnInput        bool
	ReturnOutput       bool
	Target             any
	ToolCallInvocation *ToolCallInvocation
	Meta               map[string]any
}

type ToolCallInvocation struct {
	MessageID string         `json:"messageID,omitempty"`
	ItemID    string         `json:"itemID,omitempty"`
	ToolCall  types.ToolCall `json:"toolCall,omitempty"`
}

func (o CallOptions) Merge(other CallOptions) (result CallOptions) {
	result.ProgressToken = complete.Last(o.ProgressToken, other.ProgressToken)
	result.LogData = complete.MergeMap(o.LogData, other.LogData)
	result.ReturnInput = o.ReturnInput || other.ReturnInput
	result.ReturnOutput = o.ReturnOutput || other.ReturnOutput
	result.Target = complete.Last(o.Target, other.Target)
	result.ToolCallInvocation = complete.Last(o.ToolCallInvocation, other.ToolCallInvocation)
	result.Meta = complete.MergeMap(o.Meta, other.Meta)
	return
}

func (s *Service) RunHook(ctx context.Context, in, out any, target string) (hasOutput bool, _ error) {
	server, tool, _ := strings.Cut(target, "/")
	result, err := s.Call(ctx, server, tool, in)
	if err != nil {
		return false, fmt.Errorf("failed to call hook %s: %w", target, err)
	}

	if result.IsError {
		var content string
		if len(result.Content) > 0 {
			content = result.Content[0].Text
		} else {
			sc, _ := json.Marshal(result.StructuredContent)
			content = fmt.Sprintf("failed to call hook %s: %s", target, sc)
		}
		return false, errors.New(content)
	}

	if result.StructuredContent != nil {
		b, err := json.Marshal(result.StructuredContent)
		if err != nil {
			return false, fmt.Errorf("failed to marshal structured content: %w", err)
		}
		err = json.Unmarshal(b, &out)
		if err != nil {
			return false, fmt.Errorf("failed to unmarshal structured content: %w", err)
		}
		return true, nil
	}

	return false, nil
}

func (s *Service) Call(ctx context.Context, server, tool string, args any, opts ...CallOptions) (ret *types.CallResult, err error) {
	defer func() {
		if ret == nil {
			return
		}
		if ret.StructuredContent == nil && len(ret.Content) == 1 && ret.Content[0].Text != "" {
			var obj any
			if err := json.Unmarshal([]byte(ret.Content[0].Text), &obj); err == nil {
				ret.StructuredContent = obj
			}
		}
	}()

	var (
		opt              = complete.Complete(opts...)
		session          = mcp.SessionFromContext(ctx)
		config           = types.ConfigFromContext(ctx)
		logProgressStart = false
		logProgressDone  = true
	)

	target := server
	if tool != "" {
		target = server + "/" + tool
	}

	targetType := "tool"
	if _, ok := config.Agents[server]; ok {
		targetType = "agent"
	}

	if session != nil && opt.ProgressToken != nil {
		var (
			tc        types.ToolCall
			messageID string
			itemID    string
		)
		if opt.ToolCallInvocation != nil {
			tc = opt.ToolCallInvocation.ToolCall
			messageID = opt.ToolCallInvocation.MessageID
			itemID = opt.ToolCallInvocation.ItemID
		} else {
			logProgressStart = true
			tc.CallID = uuid.String()
			argsData, _ := json.Marshal(args)
			tc.Arguments = string(argsData)
			tc.Name, _ = opt.LogData["mcpToolName"].(string)
			if tc.Name == "" {
				tc.Name = target
			} else {
				logProgressStart = false
				logProgressDone = false
			}
		}
		tc.Target = target
		tc.TargetType = targetType

		if logProgressStart {
			_ = session.SendPayload(ctx, "notifications/progress", mcp.NotificationProgressRequest{
				ProgressToken: opt.ProgressToken,
				Meta: map[string]any{
					types.CompletionProgressMetaKey: types.CompletionProgress{
						MessageID: messageID,
						Item: types.CompletionItem{
							HasMore:  true,
							ID:       itemID,
							ToolCall: &tc,
						},
					},
				},
			})
		}

		if logProgressDone {
			defer func() {
				tcResult := types.ToolCallResult{
					CallID: tc.CallID,
				}
				if ret != nil {
					tcResult.Output = *ret
				}
				if err != nil {
					tcResult.Output = types.CallResult{
						IsError: true,
						Content: []mcp.Content{
							{
								Type: "text",
								Text: err.Error(),
							},
						},
					}
				}
				_ = session.SendPayload(ctx, "notifications/progress", mcp.NotificationProgressRequest{
					ProgressToken: opt.ProgressToken,
					Meta: map[string]any{
						types.CompletionProgressMetaKey: types.CompletionProgress{
							MessageID: messageID,
							Item: types.CompletionItem{
								ID:             itemID,
								ToolCall:       &tc,
								ToolCallResult: &tcResult,
							},
						},
					},
				})
			}()
		}
	}

	if _, ok := config.Agents[server]; ok && tool != types.AgentTool+server {
		return s.sampleCall(ctx, server, args, SampleCallOptions{
			ProgressToken: opt.ProgressToken,
		})
	}

	c, err := s.GetClient(ctx, server)
	if err != nil {
		return nil, err
	}

	if targetType != "agent" {
		// For tools, use the user context so that tool calls can be cancelled by the user.
		ctx = mcp.UserContext(ctx)
	}
	mcpCallResult, err := c.Call(ctx, tool, args, mcp.CallOption{
		ProgressToken: opt.ProgressToken,
		Meta:          opt.Meta,
	})
	if err != nil {
		return nil, err
	}
	return &types.CallResult{
		StructuredContent: mcpCallResult.StructuredContent,
		Content:           mcpCallResult.Content,
		IsError:           mcpCallResult.IsError,
	}, nil
}

type ListToolsOptions struct {
	Servers []string
	Tools   []string
}

type ListToolsResult struct {
	Server string     `json:"server,omitempty"`
	Tools  []mcp.Tool `json:"tools,omitempty"`
}

func (s *Service) ListTools(ctx context.Context, opts ...ListToolsOptions) (result []ListToolsResult, _ error) {
	var (
		opt    ListToolsOptions
		config = types.ConfigFromContext(ctx)
	)
	for _, o := range opts {
		for _, server := range o.Servers {
			if server != "" {
				opt.Servers = append(opt.Servers, server)
			}
		}
		for _, tool := range o.Tools {
			if tool != "" {
				opt.Tools = append(opt.Tools, tool)
			}
		}
	}

	serverList := slices.Sorted(maps.Keys(config.MCPServers))
	agentsList := slices.Sorted(maps.Keys(config.Agents))
	if len(opt.Servers) == 0 {
		opt.Servers = append(serverList, agentsList...)
	}

	for _, server := range opt.Servers {
		if !slices.Contains(serverList, server) {
			continue
		}

		c, err := s.GetClient(ctx, server)
		if err != nil {
			return nil, fmt.Errorf("failed to get client for %s: %w", server, err)
		}

		tools, err := c.ListTools(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to list tools for %s: %w", server, err)
		}

		tools = filterTools(tools, opt.Tools)

		if len(tools.Tools) == 0 {
			continue
		}

		result = append(result, ListToolsResult{
			Server: server,
			Tools:  tools.Tools,
		})
	}

	for _, agentName := range opt.Servers {
		agent, ok := config.Agents[agentName]
		if !ok {
			continue
		}

		tools := filterTools(&mcp.ListToolsResult{
			Tools: []mcp.Tool{
				{
					Name:        types.AgentTool + agentName,
					Description: agent.Description,
					InputSchema: types.ChatInputSchema,
				},
			},
		}, opt.Tools)

		if len(tools.Tools) == 0 {
			continue
		}

		result = append(result, ListToolsResult{
			Server: agentName,
			Tools:  tools.Tools,
		})
	}

	return
}

func filterTools(tools *mcp.ListToolsResult, filter []string) *mcp.ListToolsResult {
	if len(filter) == 0 {
		return tools
	}
	var filteredTools mcp.ListToolsResult
	for _, tool := range tools.Tools {
		if slices.Contains(filter, tool.Name) {
			filteredTools.Tools = append(filteredTools.Tools, tool)
		}
	}
	return &filteredTools
}

func (s *Service) getMatches(ref string, tools []ListToolsResult, opts ...types.BuildToolMappingsOptions) types.ToolMappings {
	toolRef := types.ParseToolRef(ref)
	result := types.ToolMappings{}
	opt := complete.Complete(opts...)

	for _, t := range tools {
		if t.Server != toolRef.Server {
			continue
		}
		for _, tool := range t.Tools {
			if toolRef.Tool == "" || tool.Name == toolRef.Tool {
				originalName := tool.Name
				if opt.DefaultAsToServer && toolRef.As == "" {
					toolRef.As = toolRef.Server
				}
				if toolRef.As != "" {
					tool.Name = toolRef.As
				}
				result[tool.Name] = types.TargetMapping[types.TargetTool]{
					MCPServer:  toolRef.Server,
					TargetName: originalName,
					Target: types.TargetTool{
						Tool: tool,
					},
				}
			}
		}
	}

	return result
}

func (s *Service) listToolsForReferences(ctx context.Context, toolList []string) ([]ListToolsResult, error) {
	if len(toolList) == 0 {
		return nil, nil
	}

	var (
		servers []string
	)

	for _, ref := range toolList {
		toolRef := types.ParseToolRef(ref)
		if toolRef.Server != "" {
			servers = append(servers, toolRef.Server)
		}
	}

	return s.ListTools(ctx, ListToolsOptions{
		Servers: servers,
	})
}

func (s *Service) BuildToolMappings(ctx context.Context, toolList []string, opts ...types.BuildToolMappingsOptions) (types.ToolMappings, error) {
	tools, err := s.listToolsForReferences(ctx, toolList)
	if err != nil {
		return nil, err
	}

	result := types.ToolMappings{}
	for _, ref := range toolList {
		maps.Copy(result, s.getMatches(ref, tools, opts...))
	}

	return result, nil
}

func hasOnlySampleKeys(args map[string]any) bool {
	for key := range args {
		if key != "prompt" && key != "attachments" && key != "_meta" {
			return false
		}
	}
	return true
}

func fileAttachmentPath(uri string) (string, error) {
	return fileuri.Decode(uri)
}

func attachmentPreview(attachment types.Attachment, decodedPath string) mcp.Content {
	name := attachment.Name
	if name == "" {
		name = filepath.Base(decodedPath)
	}
	if name == "" || name == "." || name == "/" {
		name = decodedPath
	}

	return mcp.Content{
		Type:     "resource_link",
		URI:      attachment.URL,
		Name:     name,
		MIMEType: attachment.MimeType,
	}
}

func buildAttachmentContextMessage(paths []string) string {
	var sb strings.Builder
	if len(paths) == 1 {
		fmt.Fprintf(&sb, "The user has attached the following file %q.\n", paths[0])
	} else {
		sb.WriteString("The user has attached the following files:\n")
		for _, path := range paths {
			fmt.Fprintf(&sb, "- %q\n", path)
		}
	}
	sb.WriteString("Use the read tool to extract file content as needed")
	return sb.String()
}

func (s *Service) convertToSampleRequest(config types.Config, agent string, args any) (*mcp.CreateMessageRequest, error) {
	var (
		sampleArgs types.SampleCallRequest
	)
	switch args := args.(type) {
	case string:
		sampleArgs.Prompt = args
	case map[string]any:
		if hasOnlySampleKeys(args) {
			if err := mcp.JSONCoerce(args, &sampleArgs); err != nil {
				return nil, fmt.Errorf("failed to marshal args: %w", err)
			}
		} else {
			if err := mcp.JSONCoerce(args, &sampleArgs.Prompt); err != nil {
				return nil, fmt.Errorf("failed to marshal args to prompt: %w", err)
			}
		}
	case *types.SampleCallRequest:
		if args != nil {
			if err := mcp.JSONCoerce(*args, &sampleArgs); err != nil {
				return nil, fmt.Errorf("failed to marshal args to prompt: %w", err)
			}
		}
	default:
		if err := mcp.JSONCoerce(args, &sampleArgs); err != nil {
			return nil, fmt.Errorf("failed to marshal args to prompt: %w", err)
		}
	}

	var sampleRequest = mcp.CreateMessageRequest{
		MaxTokens: config.Agents[agent].MaxTokens,
		ModelPreferences: mcp.ModelPreferences{
			Hints: []mcp.ModelHint{
				{Name: agent},
			},
		},
	}

	previewMessageIndex := -1
	if sampleArgs.Prompt != "" {
		sampleRequest.Messages = append(sampleRequest.Messages, mcp.SamplingMessage{
			Role: "user",
			Content: []mcp.Content{{
				Type: "text",
				Text: sampleArgs.Prompt,
			}},
		})
		previewMessageIndex = len(sampleRequest.Messages) - 1
	}

	var (
		filePaths    []string
		filePreviews []mcp.Content
		seenFilePath = map[string]struct{}{}
	)

	for _, attachment := range sampleArgs.Attachments {
		if strings.HasPrefix(attachment.URL, "file:///") {
			path, err := fileuri.Decode(attachment.URL)
			if err != nil {
				return nil, err
			}

			if _, seen := seenFilePath[path]; seen {
				continue
			}

			seenFilePath[path] = struct{}{}
			filePaths = append(filePaths, path)
			filePreviews = append(filePreviews, attachmentPreview(attachment, path))
			continue
		}

		if !strings.HasPrefix(attachment.URL, "data:") {
			return nil, fmt.Errorf("invalid attachment URL: %s, only data URI and file:/// URIs are supported", attachment.URL)
		}
		parts := strings.Split(strings.TrimPrefix(attachment.URL, "data:"), "base64,")
		if len(parts) != 2 {
			return nil, fmt.Errorf("invalid attachment URL: %s, only data URI and file:/// URIs are supported", attachment.URL)
		}
		mimeType := strings.Split(parts[0], ";")[0]
		if mimeType == "" {
			mimeType = attachment.MimeType
		}
		data := parts[1]
		if mimeType == "" || strings.HasPrefix(mimeType, "image/") {
			sampleRequest.Messages = append(sampleRequest.Messages, mcp.SamplingMessage{
				Role: "user",
				Content: []mcp.Content{{
					Name:     attachment.Name,
					Type:     "image",
					Data:     data,
					MIMEType: mimeType,
				}},
			})
		} else {
			sampleRequest.Messages = append(sampleRequest.Messages, mcp.SamplingMessage{
				Role: "user",
				Content: []mcp.Content{{
					Type: "resource",
					Resource: &mcp.EmbeddedResource{
						Name:     attachment.Name,
						MIMEType: mimeType,
						Blob:     data,
						Annotations: &mcp.ResourceAnnotations{
							Audience: []string{"assistant"},
						},
					},
				}},
			})
		}
	}

	if len(filePreviews) > 0 {
		if previewMessageIndex == -1 {
			sampleRequest.Messages = append(sampleRequest.Messages, mcp.SamplingMessage{
				Role:    "user",
				Content: filePreviews,
			})
		} else {
			sampleRequest.Messages[previewMessageIndex].Content = append(sampleRequest.Messages[previewMessageIndex].Content, filePreviews...)
		}
	}

	if len(filePaths) > 0 {
		sampleRequest.Messages = append(sampleRequest.Messages, mcp.SamplingMessage{
			Role: "user",
			Content: []mcp.Content{{
				Type: "text",
				Text: buildAttachmentContextMessage(filePaths),
				Meta: map[string]any{
					types.AttachmentMetaKey: true,
				},
			}},
		})
	}

	return &sampleRequest, nil
}

type SampleCallOptions struct {
	ProgressToken any
}

func (s SampleCallOptions) Merge(other SampleCallOptions) (result SampleCallOptions) {
	result.ProgressToken = complete.Last(s.ProgressToken, other.ProgressToken)
	return
}
