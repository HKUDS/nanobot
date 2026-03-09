package fswatch

import (
	"context"
	"encoding/json"
	"errors"
	"sync"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

// Subscription holds the session reference and subscribed URIs for that session.
type Subscription struct {
	session *mcp.Session
	uris    map[string]struct{}
}

// SubscriptionManager manages resource subscriptions and sends MCP notifications.
type SubscriptionManager struct {
	mu            sync.RWMutex
	subscriptions map[string]*Subscription // sessionID -> Subscription
	sessions      map[string]*mcp.Session  // sessionID -> session (all initialized sessions)
	ctx           context.Context
}

// NewSubscriptionManager creates a new SubscriptionManager.
func NewSubscriptionManager(ctx context.Context) *SubscriptionManager {
	if ctx == nil {
		ctx = context.Background()
	}
	return &SubscriptionManager{
		subscriptions: make(map[string]*Subscription),
		sessions:      make(map[string]*mcp.Session),
		ctx:           ctx,
	}
}

// AddSession registers a session for list_changed notifications.
func (sm *SubscriptionManager) AddSession(sessionID string, session *mcp.Session) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.sessions[sessionID] = session

	// Clean up when session ends
	context.AfterFunc(session.Context(), func() {
		sm.mu.Lock()
		delete(sm.sessions, sessionID)
		delete(sm.subscriptions, sessionID)
		sm.mu.Unlock()
	})
}

// Subscribe adds a URI subscription for a session.
func (sm *SubscriptionManager) Subscribe(sessionID string, session *mcp.Session, uri string) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sub, ok := sm.subscriptions[sessionID]
	if !ok {
		sub = &Subscription{
			session: session,
			uris:    make(map[string]struct{}),
		}
		sm.subscriptions[sessionID] = sub

		// Only set up cleanup if session is not nil
		if session != nil {
			context.AfterFunc(session.Context(), func() {
				sm.mu.Lock()
				delete(sm.subscriptions, sessionID)
				sm.mu.Unlock()
			})
		}
	}
	sub.uris[uri] = struct{}{}
}

// Unsubscribe removes a URI subscription for a session.
func (sm *SubscriptionManager) Unsubscribe(sessionID string, uri string) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sub, ok := sm.subscriptions[sessionID]
	if !ok {
		return
	}

	delete(sub.uris, uri)

	// Clean up empty subscription entries
	if len(sub.uris) == 0 {
		delete(sm.subscriptions, sessionID)
	}
}

// SendResourceUpdatedNotification sends a notifications/resources/updated message to sessions subscribed to the given URI.
func (sm *SubscriptionManager) SendResourceUpdatedNotification(uri string) {
	sm.mu.RLock()
	var sessionsToNotify []*mcp.Session
	for _, sub := range sm.subscriptions {
		if _, ok := sub.uris[uri]; ok {
			sessionsToNotify = append(sessionsToNotify, sub.session)
		}
	}
	sm.mu.RUnlock()

	notification := mcp.Message{
		JSONRPC: "2.0",
		Method:  "notifications/resources/updated",
	}

	params := struct {
		URI string `json:"uri"`
	}{
		URI: uri,
	}

	paramsBytes, err := json.Marshal(params)
	if err != nil {
		slog.Error("failed to marshal notification params", "error", err)
		return
	}
	notification.Params = paramsBytes

	for _, session := range sessionsToNotify {
		if err := session.Send(sm.ctx, notification); err != nil {
			slog.Error("failed to send resource updated notification", "error", err)
		}
	}
}

// SendListChangedNotification sends a notifications/resources/list_changed message to all sessions.
func (sm *SubscriptionManager) SendListChangedNotification() {
	notification := mcp.Message{
		JSONRPC: "2.0",
		Method:  "notifications/resources/list_changed",
	}

	sm.mu.RLock()
	sessions := make([]*mcp.Session, 0, len(sm.sessions))
	for _, session := range sm.sessions {
		sessions = append(sessions, session)
	}
	sm.mu.RUnlock()

	for _, session := range sessions {
		if err := session.Send(sm.ctx, notification); err != nil && !errors.Is(err, mcp.ErrNoReader) {
			slog.Error("failed to send list_changed notification", "error", err)
		}
	}
}

// AutoUnsubscribe removes a URI from all subscriptions (used when a resource is deleted).
func (sm *SubscriptionManager) AutoUnsubscribe(uri string) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	for _, sub := range sm.subscriptions {
		delete(sub.uris, uri)
	}
}
