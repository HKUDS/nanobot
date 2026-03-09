package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/log"
)

const (
	SessionIDHeader = "Mcp-Session-Id"

	// Token type URNs for RFC 8693 Token Exchange
	tokenTypeJWT    = "urn:ietf:params:oauth:token-type:jwt"
	tokenTypeAPIKey = "urn:obot:token-type:api-key"
)

// isJWT checks if the given token appears to be a JWT by validating its structure.
func isJWT(token string) bool {
	parser := jwt.NewParser()
	_, _, err := parser.ParseUnverified(token, jwt.MapClaims{})
	return err == nil
}

type HTTPClient struct {
	ctx          context.Context
	cancel       context.CancelCauseFunc
	clientLock   sync.RWMutex
	httpClient   *http.Client
	handler      WireHandler
	oauthHandler *oauth
	baseURL      string
	messageURL   string
	serverName   string
	displayName  string
	headers      map[string]string
	waiter       *waiter
	sse          bool

	tokenExchangeEndpoint     string
	tokenExchangeClientID     string
	tokenExchangeClientSecret string

	initializeLock    sync.RWMutex
	initializeRequest *Message
	sessionID         *string

	sseLock       sync.RWMutex
	needReconnect bool
}

type HTTPClientOptions struct {
	OAuthClientName           string
	OAuthRedirectURL          string
	CallbackHandler           CallbackHandler
	ClientCredLookup          ClientCredLookup
	TokenStorage              TokenStorage
	TokenExchangeEndpoint     string
	TokenExchangeClientID     string
	TokenExchangeClientSecret string
}

func newHTTPClient(serverName string, config Server, opts HTTPClientOptions, sessionState *SessionState, headers map[string]string, watchesEvents bool) (*HTTPClient, error) {
	var sessionID *string
	if id := headers[SessionIDHeader]; id != "" {
		sessionID = &id
	} else if sessionState != nil {
		sessionID = &sessionState.ID
	}

	var initializeRequest *Message
	if sessionState != nil {
		var err error
		initializeRequest, err = NewMessage("initialize", sessionState.InitializeRequest)
		if err != nil {
			return nil, err
		}
	}

	return &HTTPClient{
		httpClient:        http.DefaultClient,
		oauthHandler:      newOAuth(opts.CallbackHandler, opts.ClientCredLookup, opts.TokenStorage, opts.OAuthClientName, opts.OAuthRedirectURL),
		baseURL:           config.BaseURL,
		messageURL:        config.BaseURL,
		serverName:        serverName,
		displayName:       complete.First(config.Name, config.ShortName, serverName),
		headers:           maps.Clone(headers),
		waiter:            newWaiter(),
		needReconnect:     watchesEvents,
		sessionID:         sessionID,
		initializeRequest: initializeRequest,

		tokenExchangeClientID:     opts.TokenExchangeClientID,
		tokenExchangeClientSecret: opts.TokenExchangeClientSecret,
		tokenExchangeEndpoint:     opts.TokenExchangeEndpoint,
	}, nil
}

func (s *HTTPClient) SetOAuthCallbackHandler(handler CallbackHandler) {
	s.oauthHandler.callbackHandler = handler
}

func (s *HTTPClient) SessionID() string {
	s.initializeLock.RLock()
	defer s.initializeLock.RUnlock()

	if s.sessionID == nil {
		return ""
	}
	return *s.sessionID
}

func (s *HTTPClient) Close(deleteSession bool) {
	sessionID := s.SessionID()
	slog.Info("mcp client closing", "server", s.serverName, "session_id", sessionID, "delete_session", deleteSession)

	if deleteSession {
		s.initializeLock.RLock()
		sessionID := s.sessionID
		s.initializeLock.RUnlock()

		if sessionID != nil && *sessionID != "" {
			// If we have a session ID, then we need to send a close message to
			// the server to clean up the session.
			s.clientLock.RLock()
			httpClient := s.httpClient
			s.clientLock.RUnlock()

			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			req, err := s.newRequest(ctx, http.MethodDelete, nil)
			if err != nil {
				slog.Error("failed to create close request", "error", err)
				return
			}

			resp, err := httpClient.Do(req)
			if err != nil {
				// Best effort
				slog.Error("failed to send close request", "error", err)
				return
			}
			resp.Body.Close()
		}
	}

	if s.cancel != nil {
		sid := ""
		if s.sessionID != nil {
			sid = *s.sessionID
		}
		s.cancel(fmt.Errorf("http client closed session: %v, deleteSession=%v", sid, deleteSession))
	}
	s.waiter.Close()
}

func (s *HTTPClient) Wait() {
	s.waiter.Wait()
}

func (s *HTTPClient) newRequest(ctx context.Context, method string, in any) (*http.Request, error) {
	var body io.Reader
	if in != nil {
		data, err := json.Marshal(in)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal message: %w", err)
		}
		body = bytes.NewBuffer(data)
		log.Messages(ctx, s.serverName, true, data)
	}

	u := s.messageURL
	if method == http.MethodGet || u == "" {
		// If this is a GET request, then it is starting the SSE stream.
		// In this case, we need to use the base URL instead.
		u = s.baseURL
	}

	req, err := http.NewRequestWithContext(ctx, method, u, body)
	if err != nil {
		return nil, err
	}

	for k, v := range s.headers {
		req.Header.Set(k, v)
	}

	// Perform token exchange if configured and a token was parsed
	// Check for a token on the context
	token := TokenFromContext(ctx)
	if token != "" {
		// Exchange the token
		exchangedToken, err := s.exchangeToken(ctx, token)
		if err != nil {
			return nil, fmt.Errorf("failed to exchange token: %w", err)
		}

		if exchangedToken != "" {
			req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", exchangedToken))
		}
	}

	s.initializeLock.RLock()
	if s.sessionID != nil && *s.sessionID != "" {
		req.Header.Set(SessionIDHeader, *s.sessionID)
	}
	s.initializeLock.RUnlock()

	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Accept-Encoding", "identity") // Disable compression
	if method != http.MethodGet {
		// Don't add because some *cough* CloudFront *cough* proxies don't like it
		req.Header.Set("Accept", "application/json, text/event-stream")
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	return req, nil
}

func (s *HTTPClient) ensureSSE(ctx context.Context, msg *Message, lastEventID string) error {
	s.sseLock.RLock()
	if !s.needReconnect {
		s.sseLock.RUnlock()
		return nil
	}
	s.sseLock.RUnlock()

	// Hold the lock while we try to start the SSE endpoint.
	// We need to make sure that the message URL is set before continuing.
	s.sseLock.Lock()
	defer s.sseLock.Unlock()

	if !s.needReconnect {
		// Check again in case SSE was started while we were waiting for the lock.
		return nil
	}

	slog.Info("mcp client connecting event stream",
		"server", s.serverName,
		"session_id", s.SessionID(),
		"last_event_id", lastEventID)

	// Start the SSE stream with the managed context.
	req, err := s.newRequest(s.ctx, http.MethodGet, nil)
	if err != nil {
		return err
	}

	if lastEventID != "" {
		req.Header.Set("Last-Event-ID", lastEventID)
	}

	s.clientLock.RLock()
	httpClient := s.httpClient
	s.clientLock.RUnlock()

	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}

	if resp.StatusCode == http.StatusUnauthorized {
		body, _ := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		return AuthRequiredErr{
			ProtectedResourceValue: resp.Header.Get("WWW-Authenticate"),
			Err:                    fmt.Errorf("failed to connect to SSE server: %s: %s", resp.Status, body),
		}
	}

	if resp.StatusCode == http.StatusNotFound && !s.sse {
		body, _ := io.ReadAll(resp.Body)
		_ = resp.Body.Close()

		s.initializeLock.RLock()
		defer s.initializeLock.RUnlock()

		id := ""
		if s.sessionID != nil {
			id = *s.sessionID
		}
		return SessionNotFoundErr{
			SessionID: id,
			Err:       fmt.Errorf("failed to connect to SSE server: %s: %s", resp.Status, body),
		}
	}

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		// If msg is nil, then this is an SSE request for HTTP streaming.
		// If the server doesn't support a separate SSE endpoint, then we can just return.
		// The spec indicates that a server should return 405 if the request method is not allowed.
		// However, some servers return a 404.
		if !s.sse && (resp.StatusCode == http.StatusMethodNotAllowed || resp.StatusCode == http.StatusNotFound) {
			s.needReconnect = false
			return nil
		}
		return fmt.Errorf("failed to connect to SSE server url %s: %s, %s", req.URL.String(), resp.Status, string(body))
	}

	s.needReconnect = false
	slog.Info("mcp client event stream connected",
		"server", s.serverName,
		"session_id", s.SessionID(),
		"status_code", resp.StatusCode)

	gotResponse := make(chan error, 1)
	go func() (err error, send bool) {
		defer func() {
			if err != nil {
				s.sseLock.Lock()
				s.needReconnect = true
				s.sseLock.Unlock()

				// If we get an error, then we aren't reconnecting to the SSE endpoint.
				if send {
					gotResponse <- err
				}
			}

			resp.Body.Close()
		}()

		messages := newSSEStream(resp.Body)

		if s.sse {
			_, data, ok := messages.readNextMessage("endpoint")
			if !ok {
				return fmt.Errorf("failed to read SSE message: %w", messages.err()), true
			}

			baseURL, err := url.Parse(s.baseURL)
			if err != nil {
				return fmt.Errorf("failed to parse SSE URL: %w", err), true
			}

			u, err := url.Parse(data)
			if err != nil {
				return fmt.Errorf("failed to parse returned SSE URL: %w", err), true
			}

			baseURL.Path = u.Path
			baseURL.RawQuery = u.RawQuery
			s.messageURL = baseURL.String()

			initReq, err := s.newRequest(ctx, http.MethodPost, msg)
			if err != nil {
				return fmt.Errorf("failed to create initialize message req: %w", err), true
			}

			s.clientLock.RLock()
			httpClient = s.httpClient
			s.clientLock.RUnlock()

			initResp, err := httpClient.Do(initReq)
			if err != nil {
				return fmt.Errorf("failed to POST initialize message: %w", err), true
			}
			body, _ := io.ReadAll(initResp.Body)
			_ = initResp.Body.Close()

			if initResp.StatusCode != http.StatusOK && initResp.StatusCode != http.StatusAccepted {
				return fmt.Errorf("failed to POST initialize message got status: %s: %s", initResp.Status, body), true
			}

			// Mark this client as initialized.
			s.initializeLock.Lock()
			s.sessionID = new(string)
			s.initializeRequest = msg
			s.initializeLock.Unlock()
		}

		close(gotResponse)

		for {
			seenID, message, ok := messages.readNextMessage("message")
			if seenID != "" {
				lastEventID = seenID
			}
			if !ok {
				if err := messages.err(); err != nil {
					if errors.Is(err, context.Canceled) {
						slog.Debug("context canceled reading SSE message", "error", err)
					} else {
						slog.Error("failed to read SSE message", "error", err)
					}
				}

				select {
				case <-s.ctx.Done():
					// If the context is done, then we don't need to reconnect.
					// Returning the error here will close the waiter, indicating that
					// the client is done.
					return s.ctx.Err(), false
				default:
					if msg != nil {
						msg.ID = nextMessageID()
					}
					s.sseLock.Lock()
					if !s.needReconnect {
						s.needReconnect = true
					}
					s.sseLock.Unlock()
				}

				if err := s.ensureSSE(ctx, msg, lastEventID); err != nil {
					return fmt.Errorf("failed to reconnect to SSE server: %v", err), false
				}

				return nil, false
			}

			var msg Message
			if err := json.Unmarshal([]byte(message), &msg); err != nil {
				continue
			}

			log.Messages(ctx, s.serverName, false, []byte(message))
			s.handler(s.ctx, msg)
		}
	}()

	return <-gotResponse
}

func (s *HTTPClient) Start(ctx context.Context, handler WireHandler) error {
	s.ctx, s.cancel = context.WithCancelCause(ctx)
	s.handler = handler

	if httpClient := s.oauthHandler.loadFromStorage(s.ctx, s.baseURL); httpClient != nil {
		s.httpClient = httpClient
		slog.Info("mcp client loaded oauth token from storage", "server", s.serverName)
	}

	if s.sessionID != nil {
		go func() {
			err := s.ensureSSE(ctx, nil, "")
			if err != nil {
				slog.Error("failed to re-initialize SSE", "error", err)
			}
		}()
	}

	return nil
}

func (s *HTTPClient) initialize(ctx context.Context, msg Message) error {
	slog.Info("mcp client initializing",
		"server", s.serverName,
		"request_id", MessageIDString(msg.ID))

	req, err := s.newRequest(ctx, http.MethodPost, msg)
	if err != nil {
		return err
	}

	// Remove the session ID header if it exists because we are initializing.
	delete(req.Header, SessionIDHeader)

	s.clientLock.RLock()
	httpClient := s.httpClient
	s.clientLock.RUnlock()

	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		streamingErrorMessage, _ := io.ReadAll(resp.Body)
		return AuthRequiredErr{
			ProtectedResourceValue: resp.Header.Get("WWW-Authenticate"),
			Err:                    fmt.Errorf("failed to initialize HTTP Streaming client: %s: %s", resp.Status, streamingErrorMessage),
		}
	}

	if resp.StatusCode != http.StatusOK {
		streamingErrorMessage, _ := io.ReadAll(resp.Body)
		streamError := fmt.Errorf("failed to initialize HTTP Streaming client: %s: %s", resp.Status, streamingErrorMessage)

		s.sse = true
		s.needReconnect = true
		if err := s.ensureSSE(ctx, &msg, ""); err != nil {
			s.sse = false
			return errors.Join(streamError, err)
		}

		// The client is marked as initialized in ensureSSE after it receives a successful response to the initialize request
		// to avoid a race with marking the client as initialized here and sending the notifications/initialized message.
		return nil
	}

	sessionID := resp.Header.Get(SessionIDHeader)

	s.initializeLock.Lock()
	s.sessionID = &sessionID
	s.initializeRequest = &msg
	s.initializeLock.Unlock()
	slog.Info("mcp client initialized",
		"server", s.serverName,
		"session_id", sessionID,
		"status_code", resp.StatusCode)

	go func() {
		if err = s.ensureSSE(ctx, nil, ""); err != nil {
			slog.Error("failed to initialize SSE", "error", err)
		}
	}()

	seen, err := s.readResponse(resp)
	if err != nil {
		return fmt.Errorf("failed to decode mcp initialize response: %w", err)
	} else if !seen {
		return fmt.Errorf("no response from server, expected an initialize response")
	}

	return nil
}

func (s *HTTPClient) Send(ctx context.Context, msg Message) error {
	err := s.send(ctx, msg)
	if err == nil {
		return nil
	}

	// We need to check for various errors and handle them according the spec.

	// Check for an authentication-required error and put the user through the OAuth process.
	if oauthErr, ok := errors.AsType[AuthRequiredErr](err); ok {
		slog.Info("mcp client authentication required",
			"server", s.serverName,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID))

		// If there is an existing token, it doesn't work, so delete it.
		if err := s.oauthHandler.tokenStorage.DeleteTokenConfig(ctx, s.baseURL); err != nil {
			return fmt.Errorf("failed to delete token config: %w", err)
		}

		httpClient, err := s.oauthHandler.oauthClient(s.ctx, s, s.baseURL, oauthErr.ProtectedResourceValue)
		if err != nil || httpClient == nil {
			streamError := fmt.Errorf("failed to initialize HTTP Streaming client: %w", oauthErr)
			return errors.Join(streamError, err)
		}

		s.clientLock.Lock()
		s.httpClient = httpClient
		s.clientLock.Unlock()

		// Make the call to send instead of Send so we don't get stuck in an authentication loop.
		return s.send(ctx, msg)
	}

	// Check for a session-not-found error and re-initialize.
	var sessionNotFoundErr SessionNotFoundErr
	if errors.As(err, &sessionNotFoundErr) && sessionNotFoundErr.SessionID != "" {
		slog.Info("mcp client session not found, reinitializing",
			"server", s.serverName,
			"session_id", sessionNotFoundErr.SessionID,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID))

		s.initializeLock.Lock()
		s.sessionID = nil
		s.initializeLock.Unlock()

		// Make the call to send instead of Send so we don't get stuck in a reinitialize loop.
		return s.send(ctx, msg)
	}

	// This loop checks for errors from the oauth2 package we use for the HTTP client after authentication.
	// This is meant to catch errors such as failing to refresh the OAuth token.
	unwrappedErr := err
	for unwrappedErr != nil {
		// Continually unwrap the errors until we find one that starts with oauth2:
		if strings.HasPrefix(unwrappedErr.Error(), "oauth2:") {
			slog.Warn("mcp client oauth2 transport error, retrying unauthenticated",
				"server", s.serverName,
				"method", msg.Method,
				"request_id", MessageIDString(msg.ID),
				"error", unwrappedErr)

			// If we do find an error that starts with "oauth2:" then there was an issue with the oauth2 HTTP client.
			// Reset the HTTP client to the default and try again. Using the default client will give us the unauthenticated
			// error that we need to continue the process.

			s.clientLock.Lock()
			s.httpClient = http.DefaultClient
			s.clientLock.Unlock()

			// Use the exported Send method here so that we catch the AuthRequiredErr above on the recursed call.
			return s.Send(ctx, msg)
		}
		unwrappedErr = errors.Unwrap(unwrappedErr)
	}

	return err
}

func (s *HTTPClient) send(ctx context.Context, msg Message) error {
	s.initializeLock.RLock()
	initialized := s.sessionID != nil
	initializeMessage := s.initializeRequest
	s.initializeLock.RUnlock()

	if !initialized {
		if msg.Method != "initialize" && initializeMessage == nil {
			return fmt.Errorf("cannot send %s message because client is not initialized, must send InitializeRequest first", msg.Method)
		}

		if initializeMessage == nil {
			initializeMessage = &msg
		} else {
			initializeMessage.ID = nextMessageID()
		}
		if err := s.initialize(ctx, *initializeMessage); err != nil {
			return fmt.Errorf("failed to initialize client: %w", err)
		}

		if msg.Method == "initialize" {
			// If we're sending the request to initialize, then we're done.
			// Otherwise, we're reinitializing and should continue.
			return nil
		} else if err := s.send(ctx, Message{
			JSONRPC: "2.0",
			Method:  "notifications/initialized",
		}); err != nil {
			return fmt.Errorf("failed to send notifications/initialized: %w", err)
		}
	}

	errChan := make(chan error, 1)
	go func() {
		defer close(errChan)
		// Ensure that the SSE connection is still active.
		if err := s.ensureSSE(ctx, initializeMessage, ""); err != nil {
			errChan <- fmt.Errorf("failed to restart SSE: %w", err)
		}
	}()

	if s.sse {
		// If this is an SSE-based MCP server, then we have to wait for the SSE connection to be established.
		if err := <-errChan; err != nil {
			return err
		}
	} else {
		// If not, then keep going. It will reconnect, if necessary.
		go func() {
			if err := <-errChan; err != nil {
				slog.Error("sse error", "error", err)
			}
		}()
	}

	req, err := s.newRequest(ctx, http.MethodPost, msg)
	if err != nil {
		return err
	}

	if slog.Default().Enabled(ctx, slog.LevelDebug) {
		slog.Debug("mcp client sending request",
			"server", s.serverName,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID),
			"call_identifier", getMessageName(&msg),
			"session_id", req.Header.Get(SessionIDHeader))
	}

	s.clientLock.RLock()
	httpClient := s.httpClient
	s.clientLock.RUnlock()

	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		streamingErrorMessage, _ := io.ReadAll(resp.Body)
		slog.Warn("mcp client request unauthorized",
			"server", s.serverName,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID),
			"status_code", resp.StatusCode)
		return AuthRequiredErr{
			ProtectedResourceValue: resp.Header.Get("WWW-Authenticate"),
			Err:                    fmt.Errorf("failed to send message: %s: %s", resp.Status, streamingErrorMessage),
		}
	}

	if resp.StatusCode == http.StatusNotFound {
		streamingErrorMessage, _ := io.ReadAll(resp.Body)
		slog.Warn("mcp client request session not found",
			"server", s.serverName,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID),
			"session_id", req.Header.Get(SessionIDHeader),
			"status_code", resp.StatusCode)
		return SessionNotFoundErr{
			SessionID: req.Header.Get(SessionIDHeader),
			Err:       fmt.Errorf("failed to send message: %s: %s", resp.Status, streamingErrorMessage),
		}
	}

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusAccepted {
		streamingErrorMessage, _ := io.ReadAll(resp.Body)
		slog.Error("mcp client request failed",
			"server", s.serverName,
			"method", msg.Method,
			"request_id", MessageIDString(msg.ID),
			"status_code", resp.StatusCode)
		return fmt.Errorf("failed to send message: %s: %s", resp.Status, streamingErrorMessage)
	}

	slog.Debug("mcp client request accepted",
		"server", s.serverName,
		"method", msg.Method,
		"request_id", MessageIDString(msg.ID),
		"status_code", resp.StatusCode)

	if s.sse || resp.StatusCode == http.StatusAccepted {
		return nil
	}

	_, err = s.readResponse(resp)
	return err
}

func (s *HTTPClient) readResponse(resp *http.Response) (bool, error) {
	var seen bool
	handle := func(message *Message) {
		seen = true
		go s.handler(s.ctx, *message)
	}

	if resp.Header.Get("Content-Type") == "text/event-stream" {
		stream := newSSEStream(resp.Body)
		for {
			_, data, ok := stream.readNextMessage("message")
			if !ok {
				return seen, nil
			}

			var message Message
			if err := json.Unmarshal([]byte(data), &message); err != nil {
				return seen, fmt.Errorf("failed to decode response: %w", err)
			}

			log.Messages(s.ctx, s.serverName, false, []byte(data))
			handle(&message)
		}
	}

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return seen, fmt.Errorf("failed to read response body: %w", err)
	}

	if len(data) == 0 {
		return false, nil
	}

	if data[0] != '{' {
		return false, fmt.Errorf("invalid response format, expected JSON object, got: %s", data)
	}

	var message Message
	if err := json.Unmarshal(data, &message); err != nil {
		return false, fmt.Errorf("failed to decode response: %w", err)
	}

	log.Messages(s.ctx, s.serverName, false, data)
	handle(&message)
	return seen, nil
}

type SSEStream struct {
	lines *bufio.Scanner
}

func newSSEStream(input io.Reader) *SSEStream {
	lines := bufio.NewScanner(input)
	lines.Buffer(make([]byte, 0, 1024), 10*1024*1024)
	return &SSEStream{
		lines: lines,
	}
}

func (s *SSEStream) err() error {
	return s.lines.Err()
}

func (s *SSEStream) readNextMessage(expectedEventName string) (string, string, bool) {
	var (
		eventName string
		id        string
		data      string
	)
	for s.lines.Scan() {
		line := s.lines.Text()
		if len(line) == 0 {
			if data != "" && (eventName == expectedEventName || (eventName == "" && expectedEventName == "message")) {
				return id, data[:len(data)-1], true
			}
			eventName = ""
			id = ""
			data = ""
			continue
		}

		k, v, ok := cutSSELine(line)
		if !ok {
			continue
		}

		switch k {
		case "id":
			id = v
		case "data":
			data += v + "\n"
		case "event":
			eventName = v
		}
	}

	return id, "", false
}

func cutSSELine(line string) (string, string, bool) {
	key, value, ok := strings.Cut(line, ":")
	if !ok {
		return "", "", false
	}
	return key, strings.TrimPrefix(value, " "), true
}

// exchangeToken performs OAuth 2.0 Token Exchange (RFC 8693) with the authorization server.
// It exchanges the subject token for an access token.
// Returns the exchanged access token or an error. If the endpoint returns 404, returns (empty string, nil).
func (s *HTTPClient) exchangeToken(ctx context.Context, subjectToken string) (string, error) {
	if s.tokenExchangeEndpoint == "" {
		// Don't error. Maybe OAuth is configured.
		return "", nil
	}

	// Build the token exchange request according to RFC 8693
	data := url.Values{}
	data.Set("grant_type", "urn:ietf:params:oauth:grant-type:token-exchange")
	data.Set("subject_token", subjectToken)

	// Detect token type based on format
	subjectTokenType := tokenTypeAPIKey
	if isJWT(subjectToken) {
		subjectTokenType = tokenTypeJWT
	}
	slog.Info("mcp client token exchange requested",
		"server", s.serverName,
		"token_type", subjectTokenType,
		"endpoint", s.tokenExchangeEndpoint)
	data.Set("subject_token_type", subjectTokenType)
	data.Set("requested_token_type", "urn:ietf:params:oauth:token-type:access_token")
	data.Set("resource", s.baseURL)

	// Create the HTTP request
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.tokenExchangeEndpoint, strings.NewReader(data.Encode()))
	if err != nil {
		return "", fmt.Errorf("failed to create token exchange request: %w", err)
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	// Add HTTP Basic authentication if client credentials are configured
	if s.tokenExchangeClientID != "" || s.tokenExchangeClientSecret != "" {
		req.SetBasicAuth(s.tokenExchangeClientID, s.tokenExchangeClientSecret)
	}

	// Make the request
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to call token exchange endpoint: %w", err)
	}
	defer resp.Body.Close()

	// If the response status code is not OK, then continue without a token.
	// Maybe OAuth will work.
	if resp.StatusCode != http.StatusOK {
		slog.Debug("token exchange endpoint returned non-200 status", "endpoint", s.tokenExchangeEndpoint, "status_code", resp.StatusCode)
		return "", nil
	}

	// Parse successful response
	var tokenResp struct {
		AccessToken     string `json:"access_token"`
		IssuedTokenType string `json:"issued_token_type"`
		TokenType       string `json:"token_type"`
		ExpiresIn       int    `json:"expires_in"`
		Scope           string `json:"scope"`
		RefreshToken    string `json:"refresh_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&tokenResp); err != nil {
		return "", fmt.Errorf("failed to parse token exchange response: %w", err)
	}

	if tokenResp.AccessToken == "" {
		return "", fmt.Errorf("token exchange response missing access_token")
	}

	return tokenResp.AccessToken, nil
}
