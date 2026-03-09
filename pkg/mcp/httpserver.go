package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
	"github.com/tidwall/gjson"
)

// responseRecorder is an http.ResponseWriter that captures the response for audit logging
type responseRecorder struct {
	http.ResponseWriter
	statusCode int
	body       bytes.Buffer
}

func newResponseRecorder(w http.ResponseWriter) *responseRecorder {
	return &responseRecorder{
		ResponseWriter: w,
		statusCode:     http.StatusOK,
	}
}

func (r *responseRecorder) WriteHeader(code int) {
	r.statusCode = code
	r.ResponseWriter.WriteHeader(code)
}

func (r *responseRecorder) Write(b []byte) (int, error) {
	r.body.Write(b)
	return r.ResponseWriter.Write(b)
}

func (r *responseRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// sensitiveHeaders contains headers that should be redacted from audit logs
var sensitiveHeaders = map[string]struct{}{
	"Authorization":       {},
	"Cookie":              {},
	"Set-Cookie":          {},
	"X-Api-Key":           {},
	"X-Auth-Token":        {},
	"Proxy-Authorization": {},
}

func buildAuditLog(req *http.Request, method string, sessionID string) auditlogs.MCPAuditLog {
	startTime := time.Now()

	clientIP := req.RemoteAddr
	if forwarded := req.Header.Get("X-Forwarded-For"); forwarded != "" {
		clientIP = strings.Split(forwarded, ",")[0]
	}

	// Extract and redact API key from Authorization header
	var redactedAPIKey string
	if authHeader := req.Header.Get("Authorization"); authHeader != "" {
		if token, ok := strings.CutPrefix(authHeader, "Bearer "); ok && !isJWT(token) {
			redactedAPIKey = auditlogs.RedactAPIKey(token)
		}
	}

	// Copy headers and redact sensitive values
	sanitizedHeaders := make(http.Header, len(req.Header))
	for k, v := range req.Header {
		if _, sensitive := sensitiveHeaders[k]; sensitive {
			sanitizedHeaders[k] = []string{"[REDACTED]"}
		} else {
			sanitizedHeaders[k] = v
		}
	}
	headersJSON, _ := json.Marshal(sanitizedHeaders)

	return auditlogs.MCPAuditLog{
		CreatedAt:      startTime,
		ClientIP:       strings.TrimSpace(clientIP),
		CallType:       method,
		SessionID:      sessionID,
		APIKey:         redactedAPIKey,
		UserAgent:      req.Header.Get("User-Agent"),
		RequestHeaders: headersJSON,
	}
}

type HTTPServer struct {
	mux                       *http.ServeMux
	protectedResourceMetadata *protectedResourceMetadata
	envProvider               func() (map[string]string, error)
	MessageHandler            MessageHandler
	sessions                  SessionStore
	ctx                       context.Context
	healthzPath               string

	// internal health check state
	internalSession *ServerSession
	healthErr       *error
	healthMu        sync.RWMutex

	auditLogCollector *auditlogs.Collector
}

type HTTPServerOptions struct {
	SessionStore      SessionStore
	BaseContext       context.Context
	HealthCheckPath   string
	ResourceName      string
	RunHealthChecker  bool
	AuditLogCollector *auditlogs.Collector
}

func (h HTTPServerOptions) Complete() HTTPServerOptions {
	if h.SessionStore == nil {
		h.SessionStore = NewInMemorySessionStore()
	}
	if h.BaseContext == nil {
		h.BaseContext = context.Background()
	}

	if h.ResourceName == "" {
		h.ResourceName = "Nanobot MCP Server"
	}
	return h
}

func (h HTTPServerOptions) Merge(other HTTPServerOptions) (result HTTPServerOptions) {
	h.SessionStore = complete.Last(h.SessionStore, other.SessionStore)
	h.BaseContext = complete.Last(h.BaseContext, other.BaseContext)
	h.RunHealthChecker = complete.Last(h.RunHealthChecker, other.RunHealthChecker)
	h.HealthCheckPath = complete.Last(h.HealthCheckPath, other.HealthCheckPath)
	h.ResourceName = complete.Last(h.ResourceName, other.ResourceName)
	h.AuditLogCollector = complete.Last(h.AuditLogCollector, other.AuditLogCollector)
	return h
}

func NewHTTPServer(ctx context.Context, envProvider func() (map[string]string, error), handler MessageHandler, opts ...HTTPServerOptions) (*HTTPServer, error) {
	o := complete.Complete(opts...)
	h := &HTTPServer{
		MessageHandler:    handler,
		mux:               http.NewServeMux(),
		envProvider:       envProvider,
		sessions:          o.SessionStore,
		ctx:               o.BaseContext,
		auditLogCollector: o.AuditLogCollector,
	}

	if o.HealthCheckPath != "" {
		h.mux.HandleFunc("GET /"+strings.TrimPrefix(o.HealthCheckPath, "/"), h.healthz)
	}

	if o.RunHealthChecker {
		go h.runHealthTicker()
	} else {
		h.healthErr = new(error)
	}

	h.mux.HandleFunc("/", h.serveHTTP)

	return h, nil
}

func (h *HTTPServer) streamEvents(rw http.ResponseWriter, req *http.Request, auditLog auditlogs.MCPAuditLog) {
	id := auditLog.SessionID
	if id == "" {
		id = req.URL.Query().Get("id")
		auditLog.SessionID = id
	}

	if id == "" {
		auditLog.ResponseStatus = http.StatusBadRequest
		auditLog.Error = "Session ID is required"
		h.auditLogCollector.CollectMCPAuditEntry(auditLog)

		http.Error(rw, "Session ID is required", http.StatusBadRequest)
		return
	}
	slog.Debug("mcp server opening event stream", "session_id", id, "path", req.URL.Path)

	session, ok, err := h.sessions.Acquire(req.Context(), h.MessageHandler, id)
	if err != nil {
		slog.Error("mcp server failed to acquire session for event stream", "session_id", id, "error", err)
		http.Error(rw, "Failed to load session: "+err.Error(), http.StatusInternalServerError)
		return
	}
	if !ok {
		auditLog.ResponseStatus = http.StatusNotFound
		auditLog.Error = "Session not found"
		h.auditLogCollector.CollectMCPAuditEntry(auditLog)

		http.Error(rw, "Session not found", http.StatusNotFound)
		return
	}
	defer h.sessions.Release(session)

	auditLog.ResponseStatus = http.StatusOK
	auditLog.ClientName = session.session.InitializeRequest.ClientInfo.Name
	auditLog.ClientVersion = session.session.InitializeRequest.ClientInfo.Version
	h.auditLogCollector.CollectMCPAuditEntry(auditLog)

	rw.Header().Set("Content-Type", "text/event-stream")
	rw.Header().Set("Cache-Control", "no-cache")
	rw.Header().Set("Connection", "keep-alive")
	rw.WriteHeader(http.StatusOK)
	if flusher, ok := rw.(http.Flusher); ok {
		flusher.Flush()
	}

	// Subscribe to the session wire using broadcast semantics. Multiple SSE
	// connections for the same session each get their own channel and every
	// message is delivered to all of them. The done channel signals session
	// closure so we don't hang after the session is torn down.
	ch, done := session.Subscribe(req.Context())

	for {
		select {
		case msg := <-ch:
			data, _ := json.Marshal(msg)
			_, err := rw.Write([]byte("data: " + string(data) + "\n\n"))
			if err != nil {
				return
			}
			if f, ok := rw.(http.Flusher); ok {
				f.Flush()
			}
		case <-done:
			slog.Debug("mcp server event stream closed", "session_id", id)
			return
		}
	}
}

type requestKey struct{}

func withRequest(req *http.Request) context.Context {
	return context.WithValue(req.Context(), requestKey{}, req)
}

func RequestFromContext(ctx context.Context) *http.Request {
	ret, _ := ctx.Value(requestKey{}).(*http.Request)
	return ret
}

func (h *HTTPServer) healthz(rw http.ResponseWriter, req *http.Request) {
	h.healthMu.RLock()
	healthErr := h.healthErr
	h.healthMu.RUnlock()

	if healthErr == nil {
		http.Error(rw, "waiting for startup", http.StatusTooEarly)
	} else if *healthErr != nil {
		http.Error(rw, (*healthErr).Error(), http.StatusServiceUnavailable)
	} else {
		rw.WriteHeader(http.StatusOK)
	}
}

func (h *HTTPServer) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
	h.mux.ServeHTTP(rw, req)
}

func (h *HTTPServer) serveHTTP(rw http.ResponseWriter, req *http.Request) {
	req = req.WithContext(withRequest(req))
	start := time.Now()
	// Determine audit log method and session ID based on HTTP method
	sessionID := h.sessions.ExtractID(req)
	slog.Debug("mcp server received http request", "http_method", req.Method, "path", req.URL.Path, "session_id", sessionID)
	var auditMethod string
	switch req.Method {
	case http.MethodGet:
		auditMethod = "sse/stream"
	case http.MethodDelete:
		auditMethod = "session/delete"
	case http.MethodPost:
		// Will be set to msg.Method after decoding the message
	default:
		slog.Warn("mcp server rejected unsupported http method", "http_method", req.Method, "path", req.URL.Path)
		http.Error(rw, `{"http_error": "Unsupported HTTP method"}`, http.StatusMethodNotAllowed)
		return
	}

	auditLog := buildAuditLog(req, auditMethod, sessionID)

	// Wrap response writer for DELETE and POST to capture response
	var recorder *responseRecorder
	if req.Method == http.MethodDelete || req.Method == http.MethodPost {
		recorder = newResponseRecorder(rw)
		rw = recorder
	}

	// Defer audit log collection for DELETE requests
	if req.Method == http.MethodDelete {
		defer func() {
			auditLog.ResponseStatus = recorder.statusCode
			responseHeaders, _ := json.Marshal(recorder.Header())
			auditLog.ResponseHeaders = responseHeaders
			auditLog.ProcessingTimeMs = time.Since(auditLog.CreatedAt).Milliseconds()
			h.auditLogCollector.CollectMCPAuditEntry(auditLog)
			slog.Debug("mcp server completed http request",
				"http_method", req.Method,
				"path", req.URL.Path,
				"session_id", sessionID,
				"status_code", recorder.statusCode,
				"duration_ms", time.Since(start).Milliseconds())
		}()
	}

	ctx := req.Context()
	auditLog.Subject = UserFromContext(ctx).Sub
	if req.Method == http.MethodGet {
		h.streamEvents(rw, req, auditLog)
		return
	}

	if sessionID != "" && req.Method == http.MethodDelete {
		sseSession, ok, err := h.sessions.LoadAndDelete(ctx, h.MessageHandler, sessionID)
		if err != nil {
			http.Error(rw, `{"http_error": "Failed to delete session"}`, http.StatusInternalServerError)
			return
		}
		if !ok {
			http.Error(rw, `{"http_error": "Session not found"}`, http.StatusNotFound)
			return
		}

		auditLog.ClientName = sseSession.session.InitializeRequest.ClientInfo.Name
		auditLog.ClientVersion = sseSession.session.InitializeRequest.ClientInfo.Version

		sseSession.Close(true)
		rw.WriteHeader(http.StatusOK)
		return
	}

	if req.Method != http.MethodPost {
		slog.Warn("mcp server rejected method", "http_method", req.Method, "path", req.URL.Path)
		http.Error(rw, `{"http_error": "Method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	ctx = WithAuditLog(ctx, &auditLog)

	var err error
	auditLog.RequestBody, err = io.ReadAll(req.Body)
	if err != nil {
		http.Error(rw, `{"http_error": "Failed to read request body"}`, http.StatusBadRequest)
		return
	}

	var msg Message
	if err := json.Unmarshal(auditLog.RequestBody, &msg); err != nil {
		slog.Warn("mcp server failed to decode request body", "path", req.URL.Path, "error", err)
		http.Error(rw, `{"http_error": "Failed to decode message"}`, http.StatusBadRequest)
		return
	}

	auditLog.CallType = msg.Method
	if msg.ID != nil {
		auditLog.RequestID = MessageIDString(msg.ID)
	}

	// Gather method-specific information.
	switch msg.Method {
	case "resources/read":
		auditLog.CallIdentifier = gjson.GetBytes(msg.Params, "uri").String()
	case "tools/call", "prompts/get":
		auditLog.CallIdentifier = gjson.GetBytes(msg.Params, "name").String()
	default:
	}
	slog.Debug("mcp server received message",
		"method", msg.Method,
		"request_id", MessageIDString(msg.ID),
		"call_identifier", auditLog.CallIdentifier,
		"session_id", sessionID)

	defer func() {
		if auditLog.ResponseStatus == 0 {
			auditLog.ResponseStatus = recorder.statusCode
		}
		auditLog.ResponseBody = recorder.body.Bytes()
		responseHeaders, _ := json.Marshal(recorder.Header())
		auditLog.ResponseHeaders = responseHeaders
		auditLog.ProcessingTimeMs = time.Since(auditLog.CreatedAt).Milliseconds()
		h.auditLogCollector.CollectMCPAuditEntry(auditLog)
		slog.Debug("mcp server completed message",
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID),
			"call_identifier", auditLog.CallIdentifier,
			"session_id", auditLog.SessionID,
			"status_code", recorder.statusCode,
			"duration_ms", time.Since(start).Milliseconds())
	}()

	if sessionID != "" {
		streamingSession, ok, err := h.sessions.Acquire(ctx, h.MessageHandler, sessionID)
		if err != nil {
			slog.Error("mcp server failed to acquire session", "session_id", sessionID, "error", err)
			http.Error(rw, `{"http_error": "Failed to load session"}`, http.StatusInternalServerError)
			return
		}
		if !ok {
			slog.Warn("mcp server session not found", "session_id", sessionID)
			http.Error(rw, `{"http_error": "Session not found"}`, http.StatusNotFound)
			return
		}
		defer h.sessions.Release(streamingSession)

		streamingSession.session.sessionManager = h.sessions

		streamingSession.session.SetEnv(h.getEnv(req))

		streamingSession.session.Set("subject", auditLog.Subject)
		streamingSession.session.Set("clientIP", auditLog.ClientIP)
		streamingSession.session.Set("apiKey", auditLog.APIKey)

		auditLog.ClientName = streamingSession.session.InitializeRequest.ClientInfo.Name
		auditLog.ClientVersion = streamingSession.session.InitializeRequest.ClientInfo.Version

		response, err := streamingSession.Exchange(ctx, msg)
		if errors.Is(err, ErrNoResponse) {
			rw.WriteHeader(http.StatusAccepted)
			return
		} else if errors.As(err, &AuthRequiredErr{}) {
			slog.Info("mcp server request requires auth", "method", msg.Method, "session_id", sessionID)
			respondWithUnauthorized(rw, req)
			return
		} else if err != nil {
			slog.Error("mcp server failed to handle message", "method", msg.Method, "request_id", MessageIDString(msg.ID), "session_id", sessionID, "error", err)
			response = Message{
				JSONRPC: msg.JSONRPC,
				ID:      msg.ID,
				Error:   ErrRPCInternal.WithError(err),
			}
		}

		rw.Header().Set("Content-Type", "application/json")

		if len(response.Result) <= 2 && response.Error == nil && strings.HasPrefix(msg.Method, "notifications/") {
			// Response has no data, write status accepted.
			rw.WriteHeader(http.StatusAccepted)
		}

		if err := json.NewEncoder(rw).Encode(response); err != nil {
			http.Error(rw, `{"http_error": "Failed to encode response"}`, http.StatusInternalServerError)
		}

		_ = h.sessions.Store(ctx, streamingSession.ID(), streamingSession)
		return
	}

	if msg.Method != "initialize" {
		slog.Warn("mcp server rejected non-initialize message without session", "method", msg.Method, "request_id", MessageIDString(msg.ID))
		http.Error(rw, fmt.Sprintf(`{"http_error": "Method not %q allowed"}`, msg.Method), http.StatusMethodNotAllowed)
		return
	}

	session, err := NewServerSession(h.ctx, h.MessageHandler, ServerSessionOptions{
		DefaultAgent: req.Header.Get("X-Nanobot-Default-Agent"),
	})
	if err != nil {
		http.Error(rw, fmt.Sprintf(`{"http_error": "Failed to create session: %v"}`, err), http.StatusInternalServerError)
		return
	}

	defer h.sessions.Release(session)

	session.session.sessionManager = h.sessions
	session.session.SetEnv(h.getEnv(req))

	resp, err := session.Exchange(ctx, msg)
	if err != nil {
		if errors.As(err, &AuthRequiredErr{}) {
			slog.Info("mcp server initialize requires auth", "request_id", MessageIDString(msg.ID))
			respondWithUnauthorized(rw, req)
			return
		}
		slog.Error("mcp server failed to initialize session", "request_id", MessageIDString(msg.ID), "error", err)
		session.Close(true)
		http.Error(rw, fmt.Sprintf(`{"http_error": "Failed to handle message: %v"}`, err), http.StatusInternalServerError)
		return
	} else if resp.Error != nil && errors.As(resp.Error, &AuthRequiredErr{}) {
		slog.Info("mcp server initialize response requires auth", "request_id", MessageIDString(msg.ID))
		respondWithUnauthorized(rw, req)
		return
	}

	auditLog.ClientName = session.session.InitializeRequest.ClientInfo.Name
	auditLog.ClientVersion = session.session.InitializeRequest.ClientInfo.Version
	auditLog.SessionID = session.ID()

	if err := h.sessions.Store(ctx, session.ID(), session); err != nil {
		slog.Error("mcp server failed to persist session", "session_id", session.ID(), "error", err)
		session.Close(true)
		http.Error(rw, fmt.Sprintf(`{"http_error": "Failed to store session: %v"}`, err), http.StatusInternalServerError)
		return
	}

	rw.Header().Set("Mcp-Session-Id", session.ID())
	rw.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(rw).Encode(resp); err != nil {
		http.Error(rw, fmt.Sprintf(`{"http_error": "Failed to encode response: %v"}`, err), http.StatusInternalServerError)
		return
	}
}

func respondWithUnauthorized(rw http.ResponseWriter, req *http.Request) {
	host := req.Header.Get("X-Forwarded-Host")
	if host == "" {
		host = req.Host
	}
	scheme := req.Header.Get("X-Forwarded-Proto")
	if scheme == "" {
		if strings.HasPrefix(host, "localhost") || strings.HasPrefix(host, "127.0.0.1") {
			scheme = "http"
		} else {
			scheme = "https"
		}
	}
	resourceMetadata := strings.TrimSuffix(fmt.Sprintf("%s://%s/.well-known/oauth-protected-resource/%s", scheme, host, strings.TrimPrefix(req.URL.Path, "/")), "/")
	slog.Info("mcp server responding unauthorized",
		"path", req.URL.Path,
		"resource_metadata", resourceMetadata)

	rw.Header().Set("WWW-Authenticate",
		strings.TrimSuffix(
			fmt.Sprintf(`Bearer error="invalid_request", error_description="Invalid access token", resource_metadata="%s"`,
				resourceMetadata,
			),
			"/"),
	)
	rw.Header().Set("Content-Type", "application/json")
	http.Error(rw, `{"http_error": "unauthorized"}`, http.StatusUnauthorized)
}

func (h *HTTPServer) runHealthTicker() {
	ctx, cancel := context.WithTimeout(h.ctx, 2*time.Minute)
	defer cancel()
	err := h.checkTools(ctx)

	h.healthMu.Lock()
	h.healthErr = &err
	h.healthMu.Unlock()

	go func() {
		for {
			h.healthMu.RLock()
			s := h.internalSession
			h.healthMu.RUnlock()

			if s == nil {
				// If the session has not been created yet, wait and try again.
				// Wait for the healthz check interval before trying again.
				time.Sleep(time.Minute)
				continue
			}

			s.Wait()

			select {
			case <-h.ctx.Done():
				return
			default:
				h.healthMu.Lock()
				h.internalSession = nil
				h.healthMu.Unlock()

				_, err := h.ensureInternalSession(h.ctx)
				h.healthMu.Lock()
				h.healthErr = &err
				h.healthMu.Unlock()
			}
		}
	}()

	timer := time.NewTimer(time.Minute)
	for {
		ctx, cancel := context.WithTimeout(h.ctx, 30*time.Second)
		err := h.checkTools(ctx)
		cancel()

		h.healthMu.Lock()
		h.healthErr = &err
		h.healthMu.Unlock()

		timer.Reset(time.Minute)
		select {
		case <-h.ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
	}
}

func (h *HTTPServer) ensureInternalSession(ctx context.Context) (*ServerSession, error) {
	h.healthMu.RLock()
	s := h.internalSession
	h.healthMu.RUnlock()
	if s != nil {
		return s, nil
	}

	session, err := NewServerSession(h.ctx, h.MessageHandler)
	if err != nil {
		return nil, err
	}

	session.session.Set("accountID", "healthcheck")

	// Set base environment on the internal session
	env, err := h.baseEnv()
	if err != nil {
		session.Close(true)
		return nil, fmt.Errorf("failed to load environment: %w", err)
	}
	session.session.SetEnv(env)

	// Initialize the session
	if _, err := session.Exchange(ctx, Message{
		JSONRPC: "2.0",
		ID:      "healthz-initialize",
		Method:  "initialize",
		Params:  []byte(`{"capabilities":{},"clientInfo":{"name":"nanobot-internal"},"protocolVersion":"2025-06-18"}`),
	}); err != nil {
		session.Close(true)
		return nil, fmt.Errorf("initialize failed: %w", err)
	}

	// Send the initialized notification
	if err = session.Send(ctx, Message{
		JSONRPC: "2.0",
		Method:  "notifications/initialized",
	}); err != nil {
		return nil, fmt.Errorf("failed to send initialized notification: %w", err)
	}

	h.sessions.Store(ctx, session.ID(), session)

	h.healthMu.Lock()
	if s = h.internalSession; s != nil {
		h.healthMu.Unlock()
		// If another goroutine already set the internal session, close this one.
		session.Close(true)
		return s, nil
	}
	h.internalSession = session
	h.healthMu.Unlock()

	return session, nil
}

func (h *HTTPServer) checkTools(ctx context.Context) error {
	session, err := h.ensureInternalSession(ctx)
	if err != nil {
		return err
	}

	env, err := h.baseEnv()
	if err != nil {
		return fmt.Errorf("failed to load environment: %w", err)
	}
	session.session.SetEnv(env)

	resp, err := session.Exchange(ctx, Message{
		JSONRPC: "2.0",
		ID:      uuid.String(),
		Method:  "tools/list",
		Params:  []byte(`{}`),
	})
	if err != nil {
		return err
	}
	if resp.Error != nil {
		return fmt.Errorf("tools/list error: %w", resp.Error)
	}

	var out ListToolsResult
	if err := json.Unmarshal(resp.Result, &out); err != nil {
		return fmt.Errorf("failed to parse tools/list result: %w", err)
	}

	if len(out.Tools) == 0 {
		return fmt.Errorf("no tools from server")
	}
	return nil
}

func (h *HTTPServer) getEnv(req *http.Request) map[string]string {
	env, err := h.baseEnv()
	if err != nil {
		slog.Error("failed to reload environment", "error", err)
		env = make(map[string]string)
	}
	token, ok := strings.CutPrefix(req.Header.Get("Authorization"), "Bearer ")
	if ok {
		env["http:bearer-token"] = token
	}
	for k, v := range req.Header {
		if key, ok := strings.CutPrefix(k, "X-Nanobot-Env-"); ok {
			env[key] = strings.Join(v, ", ")
		}
	}
	return env
}

func (h *HTTPServer) baseEnv() (map[string]string, error) {
	env := make(map[string]string)
	if h.envProvider == nil {
		return env, nil
	}

	base, err := h.envProvider()
	if err != nil {
		return nil, err
	}
	maps.Copy(env, base)
	return env, nil
}
