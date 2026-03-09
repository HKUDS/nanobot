package mcp

import (
	"context"
	"net/http"
	"sync"
)

type SessionStore interface {
	ExtractID(*http.Request) string
	Store(context.Context, string, *ServerSession) error
	Acquire(context.Context, MessageHandler, string) (*ServerSession, bool, error)
	Release(*ServerSession)
	LoadAndDelete(context.Context, MessageHandler, string) (*ServerSession, bool, error)
}

type inMemory struct {
	sessions sync.Map
}

func NewInMemorySessionStore() SessionStore {
	return &inMemory{}
}

func (s *inMemory) ExtractID(req *http.Request) string {
	return req.Header.Get("Mcp-Session-Id")
}

func (s *inMemory) Store(_ context.Context, sessionID string, session *ServerSession) error {
	s.sessions.Store(sessionID, session)
	return nil
}

func (s *inMemory) Acquire(_ context.Context, _ MessageHandler, sessionID string) (*ServerSession, bool, error) {
	if v, ok := s.sessions.Load(sessionID); ok {
		return v.(*ServerSession), true, nil
	}
	return nil, false, nil
}

func (s *inMemory) Release(*ServerSession) {
}

func (s *inMemory) LoadAndDelete(_ context.Context, _ MessageHandler, sessionID string) (*ServerSession, bool, error) {
	if v, ok := s.sessions.LoadAndDelete(sessionID); ok {
		return v.(*ServerSession), true, nil
	}
	return nil, false, nil
}
