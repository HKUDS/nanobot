package mcp

import (
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

var (
	_ Wire = (*serverWire)(nil)
	_ Wire = (*ServerSession)(nil)
)

type ServerSessionOptions struct {
	DefaultAgent string
}

func (s ServerSessionOptions) Merge(other ServerSessionOptions) ServerSessionOptions {
	s.DefaultAgent = complete.Last(s.DefaultAgent, other.DefaultAgent)
	return s
}

func NewServerSession(ctx context.Context, handler MessageHandler, opts ...ServerSessionOptions) (*ServerSession, error) {
	return NewExistingServerSession(ctx,
		SessionState{
			ID: uuid.String(),
		}, handler, opts...)
}

func NewExistingServerSession(ctx context.Context, state SessionState, handler MessageHandler, opts ...ServerSessionOptions) (*ServerSession, error) {
	opt := complete.Complete(opts...)

	s := &serverWire{
		read:      make(chan Message),
		noReader:  make(chan struct{}),
		sessionID: state.ID,
	}
	s.stopReading()

	session, err := newSession(ctx, s, handler, &state, nil, nil, SessionFromContext(ctx))
	if err != nil {
		return nil, err
	}
	for k, v := range state.Attributes {
		session.Set(k, v)
	}

	// Set the current agent if specified in options
	if opt.DefaultAgent != "" {
		session.Set("defaultAgent", SavedString(opt.DefaultAgent))
	}

	return &ServerSession{
		session: session,
		wire:    s,
	}, nil
}

type ServerSession struct {
	session *Session
	wire    *serverWire
}

// Subscribe returns a message channel and a done channel. The message channel
// receives a copy of every message sent through the server wire. Multiple
// subscribers can exist concurrently and each receives every message (broadcast
// semantics). The done channel is closed when the session is closed; callers
// must select on it to detect session shutdown.
func (s *ServerSession) Subscribe(ctx context.Context) (<-chan Message, <-chan struct{}) {
	return s.wire.subscribe(ctx)
}

func (s *ServerSession) Wait() {
	if s == nil || s.session == nil {
		return
	}
	s.session.Wait()
}

func (s *ServerSession) Start(ctx context.Context, handler WireHandler) error {
	s.wire.startReading()

	go func() {
		defer s.wire.stopReading()

		for {
			select {
			case <-ctx.Done():
				return
			case msg, ok := <-s.wire.read:
				if !ok {
					return
				}
				handler(ctx, msg)
			}
		}
	}()
	return nil
}

func (s *ServerSession) SessionID() string {
	return s.ID()
}

func (s *ServerSession) ID() string {
	if id := s.session.ID(); id != "" {
		return id
	}
	return s.wire.SessionID()
}

var (
	ErrNoResponse = errors.New("no response")
	ErrNoReader   = errors.New("no reader")
)

func (s *ServerSession) GetSession() *Session {
	return s.session
}

func (s *ServerSession) Exchange(ctx context.Context, msg Message) (Message, error) {
	isInit, err := s.session.preInit(&msg)
	if err != nil {
		return Message{}, err
	}
	resp, err := s.wire.exchange(ctx, msg)
	if err != nil {
		return Message{}, err
	}
	if isInit {
		if err := s.session.postInit(&resp); err != nil {
			return Message{}, err
		}
	}
	return resp, nil
}

func (s *ServerSession) Read(ctx context.Context) (Message, bool) {
	select {
	case msg, ok := <-s.wire.read:
		if !ok {
			return Message{}, false
		}
		return msg, true
	case <-ctx.Done():
		return Message{}, false
	}
}

func (s *ServerSession) StartReading() {
	s.wire.startReading()
}

func (s *ServerSession) StopReading() {
	s.wire.stopReading()
}

func (s *ServerSession) Send(ctx context.Context, req Message) error {
	req.Session = s.session
	go s.session.handler.OnMessage(WithSession(ctx, s.session), req)
	return nil
}

func (s *ServerSession) Close(deleteSession bool) {
	if s == nil {
		return
	}

	if s.session != nil {
		s.session.Close(deleteSession)
	}
	if s.wire != nil {
		s.wire.Close(deleteSession)
	}
}

type serverWire struct {
	ctx        context.Context
	cancel     context.CancelCauseFunc
	pending    PendingRequests
	read       chan Message
	readerLock sync.RWMutex
	noReader   chan struct{}
	handler    WireHandler
	sessionID  string

	subscriberLock sync.RWMutex
	subscribers    []chan Message
}

func (s *serverWire) SessionID() string {
	return s.sessionID
}

func (s *serverWire) exchange(ctx context.Context, msg Message) (Message, error) {
	if msg.ID == nil {
		s.handler(ctx, msg)
		return Message{}, ErrNoResponse
	}

	ch := s.pending.WaitFor(msg.ID)
	defer s.pending.Done(msg.ID)

	go func() {
		defer close(ch)
		s.handler(ctx, msg)
	}()

	select {
	case <-ctx.Done():
		return Message{}, ctx.Err()
	case <-s.ctx.Done():
		return Message{}, s.ctx.Err()
	case m, ok := <-ch:
		if !ok {
			return Message{}, ErrNoResponse
		}
		return m, nil
	}
}

func (s *serverWire) subscribe(ctx context.Context) (<-chan Message, <-chan struct{}) {
	ch := make(chan Message, 32)
	s.subscriberLock.Lock()
	s.subscribers = append(s.subscribers, ch)
	s.subscriberLock.Unlock()
	context.AfterFunc(ctx, func() {
		s.removeSubscriber(ch)
	})
	return ch, s.ctx.Done()
}

func (s *serverWire) removeSubscriber(ch chan Message) {
	s.subscriberLock.Lock()
	defer s.subscriberLock.Unlock()
	for i, sub := range s.subscribers {
		if sub == ch {
			s.subscribers = append(s.subscribers[:i], s.subscribers[i+1:]...)
			return
		}
	}
}

func (s *serverWire) Close(bool) {
	s.cancel(fmt.Errorf("session %s closed", s.sessionID))

	s.subscriberLock.Lock()
	s.subscribers = nil
	s.subscriberLock.Unlock()
}

func (s *serverWire) Wait() {
	<-s.ctx.Done()
}

func (s *serverWire) Start(ctx context.Context, handler WireHandler) error {
	s.ctx, s.cancel = context.WithCancelCause(ctx)
	s.handler = handler
	return nil
}

func (s *serverWire) Send(ctx context.Context, req Message) error {
	if s.pending.Notify(req) {
		return nil
	}

	// If there are subscribers, broadcast to all of them instead of sending
	// to the single read channel. This ensures that every SSE connection
	// sees every server-to-client message (e.g. elicitation/create).
	//
	// We hold RLock for the entire send loop. This is safe from deadlock
	// because Close() cancels s.ctx before acquiring the write lock, so any
	// blocked send here will unblock via the s.ctx.Done() case, releasing
	// the RLock and allowing Close() to proceed. Channels are never closed
	// so there is no send-on-closed-channel panic.
	s.subscriberLock.RLock()
	if len(s.subscribers) > 0 {
		defer s.subscriberLock.RUnlock()
		for _, ch := range s.subscribers {
			select {
			case ch <- req:
			case <-ctx.Done():
				return ctx.Err()
			case <-s.ctx.Done():
				return s.ctx.Err()
			}
		}
		return nil
	}
	s.subscriberLock.RUnlock()

	// No subscribers — fall back to single-reader channel. This path is
	// used by in-process connections (ServerSession.Start) where there is
	// exactly one reader on s.read.
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-s.ctx.Done():
		return s.ctx.Err()
	case <-s.noReader:
		return ErrNoReader
	case s.read <- req:
		return nil
	}
}

func (s *serverWire) startReading() {
	s.readerLock.Lock()
	defer s.readerLock.Unlock()

	s.noReader = nil
}

func (s *serverWire) stopReading() {
	s.readerLock.Lock()
	defer s.readerLock.Unlock()

	s.noReader = make(chan struct{})
	close(s.noReader)
}
