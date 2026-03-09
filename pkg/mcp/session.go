package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"reflect"
	"slices"
	"sync"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp/auditlogs"
)

var ErrNoResult = errors.New("no result in response")

type MessageHandler interface {
	OnMessage(ctx context.Context, msg Message)
}

type MessageHandlerFunc func(ctx context.Context, msg Message)

func (f MessageHandlerFunc) OnMessage(ctx context.Context, msg Message) {
	f(ctx, msg)
}

type MessageFilter func(ctx context.Context, msg *Message) (*Message, error)

type Wire interface {
	Close(deleteSession bool)
	Wait()
	Start(ctx context.Context, handler WireHandler) error
	Send(ctx context.Context, req Message) error
	SessionID() string
}

type WireHandler func(ctx context.Context, msg Message)

type Session struct {
	ctx               context.Context
	cancel            context.CancelCauseFunc
	wire              Wire
	handler           MessageHandler
	pendingRequest    PendingRequests
	InitializeResult  InitializeResult
	InitializeRequest InitializeRequest
	Parent            *Session
	HookRunner        HookRunner
	attributes        map[string]any
	lock              sync.Mutex
	filters           []filterRegistration
	filterID          int
	sessionManager    SessionStore
	hooks             Hooks

	workerLock sync.Mutex
	workers    map[any]context.CancelCauseFunc

	requestIDToProgressTokenLock sync.RWMutex
	requestIDToProgressToken     map[any]map[any]struct{}
}

type worker struct {
	ctx    context.Context
	cancel context.CancelCauseFunc
}

type filterRegistration struct {
	filter MessageFilter
	id     int
}

const SessionEnvMapKey = "env"

func (s *Session) Root() *Session {
	if s == nil {
		return nil
	}
	if s.Parent == nil {
		return s
	}
	return s.Parent.Root()
}

func (s *Session) Context() context.Context {
	return s.ctx
}

func (s *Session) Go(ctx context.Context, msg Message, f func(context.Context, Message)) {
	s.run(ctx, true, msg, f)
}

func (s *Session) Run(ctx context.Context, msg Message, f func(context.Context, Message)) {
	s.run(ctx, false, msg, f)
}

func (s *Session) run(ctx context.Context, allowConcurrent bool, msg Message, f func(context.Context, Message)) {
	parentSession := s.Root()
	sm := parentSession.sessionManager
	id := parentSession.ID()

	if allowConcurrent && sm != nil && id != "" {
		tempSession, ok, sessionErr := sm.Acquire(ctx, nil, id)
		if sessionErr == nil && ok {
			go func() {
				defer sm.Release(tempSession)

				parentSession.addRequestToProgressMapping(ctx, msg.ProgressToken())
				ctx = parentSession.addWorker(ctx, msg.ProgressToken())

				defer parentSession.removeProgressTokenMapping(ctx, msg.ProgressToken())
				defer parentSession.removeWorker(msg.ProgressToken(), nil)

				f(WithSession(ctx, s), msg)
			}()
			return
		}
	}

	msgID := msg.ID
	if id := RequestIDFromContext(ctx); id != nil {
		msgID = id
	}

	ctx = parentSession.addWorker(ctx, msgID)
	defer parentSession.removeWorker(msgID, nil)

	f(ctx, msg)
}

func (s *Session) addWorker(ctx context.Context, id any) context.Context {
	if id != nil {
		parentSession := s.Root()
		parentSession.workerLock.Lock()
		if parentSession.workers == nil {
			parentSession.workers = make(map[any]context.CancelCauseFunc, 1)
		}

		userCtx, cancel := context.WithCancelCause(ctx)
		parentSession.workers[id] = cancel
		parentSession.workerLock.Unlock()

		ctx = withUserCtx(ctx, userCtx)
	}

	return ctx
}

func (s *Session) StopAllFromRequestID(id any, reason *string) {
	parentSession := s.Root()

	parentSession.requestIDToProgressTokenLock.RLock()
	ids := slices.Collect(maps.Keys(parentSession.requestIDToProgressToken[id]))
	parentSession.requestIDToProgressTokenLock.RUnlock()

	for _, id := range ids {
		parentSession.removeWorker(id, reason)
	}

	parentSession.removeWorker(id, reason)

	parentSession.requestIDToProgressTokenLock.Lock()
	delete(s.requestIDToProgressToken, id)
	parentSession.requestIDToProgressTokenLock.Unlock()
}

func (s *Session) removeWorker(id any, reason *string) {
	if id == nil {
		return
	}

	parentSession := s.Root()

	parentSession.workerLock.Lock()
	cancel := parentSession.workers[id]
	delete(parentSession.workers, id)
	parentSession.workerLock.Unlock()

	if cancel != nil {
		var err error
		if reason != nil {
			err = &RequestCancelledError{Reason: *reason}
		}
		cancel(err)
	}
}

func (s *Session) addRequestToProgressMapping(ctx context.Context, id any) {
	msgID := RequestIDFromContext(ctx)
	if msgID != nil && id != nil {
		parentSession := s.Root()
		parentSession.requestIDToProgressTokenLock.Lock()

		if parentSession.requestIDToProgressToken == nil {
			parentSession.requestIDToProgressToken = make(map[any]map[any]struct{}, 1)
		}

		if parentSession.requestIDToProgressToken[msgID] == nil {
			parentSession.requestIDToProgressToken[msgID] = make(map[any]struct{})
		}

		parentSession.requestIDToProgressToken[msgID][id] = struct{}{}
		parentSession.requestIDToProgressTokenLock.Unlock()
	}
}

func (s *Session) removeProgressTokenMapping(ctx context.Context, id any) {
	msgID := RequestIDFromContext(ctx)
	if msgID != nil && id != nil {
		parentSession := s.Root()

		parentSession.requestIDToProgressTokenLock.Lock()
		delete(parentSession.requestIDToProgressToken[msgID], id)
		if len(parentSession.requestIDToProgressToken[msgID]) == 0 {
			delete(parentSession.requestIDToProgressToken, msgID)
		}
		parentSession.requestIDToProgressTokenLock.Unlock()
	}
}

func (s *Session) ID() string {
	if s == nil || s.wire == nil {
		return ""
	}
	return s.wire.SessionID()
}

func (s *Session) State() (*SessionState, error) {
	if s == nil {
		return nil, nil
	}

	s.lock.Lock()
	defer s.lock.Unlock()

	keys, _ := s.attributes[".keys"].([]string)
	attr := make(map[string]any, len(s.attributes))
	for k, v := range s.attributes {
		if k == ".keys" {
			continue
		} else if serializable, ok := v.(Serializable); ok {
			data, err := serializable.Serialize()
			if err != nil {
				return nil, fmt.Errorf("failed to serialize attribute %s: %w", k, err)
			}
			if data != nil {
				attr[k] = data
			}
		} else if slices.Contains(keys, k) {
			attr[k] = v
		}
	}

	return &SessionState{
		ID:                s.wire.SessionID(),
		InitializeResult:  s.InitializeResult,
		InitializeRequest: s.InitializeRequest,
		Attributes:        attr,
	}, nil
}

func (s *Session) AddEnv(kvs map[string]string) {
	if s == nil {
		return
	}

	s.lock.Lock()
	defer s.lock.Unlock()
	if s.attributes == nil {
		s.attributes = make(map[string]any)
	}
	env, ok := s.attributes[SessionEnvMapKey].(map[string]string)
	if !ok {
		env = make(map[string]string)
		s.attributes[SessionEnvMapKey] = env
	}
	maps.Copy(env, kvs)
}

func (s *Session) SetEnv(kvs map[string]string) {
	if s == nil {
		return
	}

	s.lock.Lock()
	defer s.lock.Unlock()
	if s.attributes == nil {
		s.attributes = make(map[string]any)
	}
	env := make(map[string]string)
	maps.Copy(env, kvs)
	s.attributes[SessionEnvMapKey] = env
}

func (s *Session) GetEnvMap() map[string]string {
	if s == nil {
		return map[string]string{}
	}

	result := make(map[string]string)
	s.lock.Lock()
	env, _ := s.attributes[SessionEnvMapKey].(map[string]string)
	maps.Copy(result, env)
	s.lock.Unlock()

	if s.Parent != nil {
		parentEnv := s.Parent.GetEnvMap()
		for k, v := range parentEnv {
			if _, exists := env[k]; !exists {
				result[k] = v
			}
		}
	}

	return result
}

func (s *Session) AddFilter(filter MessageFilter) (remove func()) {
	if s == nil {
		return func() {}
	}
	s.lock.Lock()
	defer s.lock.Unlock()

	id := s.filterID
	s.filterID++
	s.filters = append(s.filters, filterRegistration{
		filter: filter,
		id:     id,
	})

	return func() {
		s.lock.Lock()
		defer s.lock.Unlock()
		for i, f := range s.filters {
			if f.id == id {
				s.filters = append(s.filters[:i], s.filters[i+1:]...)
				return
			}
		}
	}
}

func (s *Session) Delete(key string) {
	if s == nil {
		return
	}
	if s.Parent != nil {
		defer s.Parent.Delete(key)
	}
	s.lock.Lock()
	defer s.lock.Unlock()
	delete(s.attributes, key)
}

func (s *Session) Set(key string, value any) {
	if s == nil {
		return
	}
	s.lock.Lock()
	defer s.lock.Unlock()
	if s.attributes == nil {
		s.attributes = make(map[string]any)
	}
	s.attributes[key] = value
}

func (s *Session) copyInto(out, in any) bool {
	dstVal := reflect.ValueOf(out)
	srcVal := reflect.ValueOf(in)
	if srcVal.Type().AssignableTo(dstVal.Type()) {
		reflect.Indirect(dstVal).Set(reflect.Indirect(srcVal))
		return true
	}

	if dstVal.Type().Kind() == reflect.Ptr && srcVal.Type().AssignableTo(dstVal.Type().Elem()) {
		dstVal.Elem().Set(srcVal)
		return true
	}

	switch v := in.(type) {
	case float64:
		if outNum, ok := out.(*float64); ok {
			*outNum = v
			return true
		}
	case SavedString:
		if outStr, ok := out.(*string); ok {
			*outStr = string(v)
			return true
		}
	case string:
		if outStr, ok := out.(*string); ok {
			*outStr = v
			return true
		}
	}

	return false
}

func (s *Session) Get(key string, out any) (ret bool) {
	if s == nil {
		return false
	}
	defer func() {
		if !ret && s != nil && s.Parent != nil {
			ret = s.Parent.Get(key, out)
		}
	}()

	s.lock.Lock()
	defer s.lock.Unlock()
	v, ok := s.attributes[key]
	if !ok {
		return false
	}

	if v == nil {
		return false
	}

	if out == nil {
		return true
	}

	if s.copyInto(out, v) {
		return true
	}

	if deserializable, ok := out.(Deserializable); ok {
		newOut, err := deserializable.Deserialize(v)
		if err != nil {
			delete(s.attributes, key)
			return false
		}
		if s.copyInto(out, newOut) {
			s.attributes[key] = newOut
			return true
		}
		return false
	}

	panic(fmt.Sprintf("can not marshal %T to type: %T", v, out))
}

func (s *Session) Attributes() map[string]any {
	if s == nil || len(s.attributes) == 0 {
		return nil
	}

	attributes := make(map[string]any)
	if s.Parent != nil {
		maps.Copy(attributes, s.Parent.Attributes())
	}

	s.lock.Lock()
	defer s.lock.Unlock()

	maps.Copy(attributes, s.attributes)
	return attributes
}

func (s *Session) Close(deleteSession bool) {
	if s.wire != nil {
		s.wire.Close(deleteSession)
	}
	s.pendingRequest.Close()
	s.cancel(fmt.Errorf("session closed: %s, delete=%v", s.ID(), deleteSession))
}

func (s *Session) Wait() {
	if s.wire == nil {
		<-s.ctx.Done()
		return
	}
	s.wire.Wait()
}

func (s *Session) normalizeProgress(progress *NotificationProgressRequest) {
	var (
		progressKey               = fmt.Sprintf("progress-token:%v", progress.ProgressToken)
		lastProgress, newProgress float64
	)

	if ok := s.Get(progressKey, &lastProgress); !ok {
		lastProgress = 0
	}

	if progress.Progress != "" {
		newF, err := progress.Progress.Float64()
		if err == nil {
			newProgress = newF
		}
	}

	if newProgress <= lastProgress {
		if progress.Total == nil {
			newProgress = lastProgress + 1
		} else {
			// If total is set then something is probably trying to make the progress pretty
			// so we don't want to just increment by 1 and mess that up.
			newProgress = lastProgress + 0.01
		}
	}
	data, err := json.Marshal(newProgress)
	if err == nil {
		progress.Progress = json.Number(data)
	}
	s.Set(progressKey, newProgress)
}

func (s *Session) SendPayload(ctx context.Context, method string, payload any) error {
	if progress, ok := payload.(NotificationProgressRequest); ok {
		s.normalizeProgress(&progress)
		payload = progress
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}
	return s.Send(ctx, Message{
		Method: method,
		Params: data,
	})
}

func (s *Session) Send(ctx context.Context, req Message) error {
	if s.wire == nil {
		return fmt.Errorf("empty session: wire is not initialized")
	}

	s.lock.Lock()
	f := slices.Clone(s.filters)
	s.lock.Unlock()

	for _, filter := range f {
		newReq, err := filter.filter(ctx, &req)
		if err != nil || newReq == nil {
			return err
		}
		req = *newReq
	}

	newReq, err := s.callAllHooks(ctx, &req, "request")
	if err != nil {
		return fmt.Errorf("failed to call \"request\" hooks: %w", err)
	}

	req = *newReq
	req.JSONRPC = "2.0"
	if err := s.wire.Send(ctx, req); err != nil {
		return err
	}
	return nil
}

type ExchangeOption struct {
	ProgressToken any
}

func (e ExchangeOption) Merge(other ExchangeOption) (result ExchangeOption) {
	result.ProgressToken = complete.Last(e.ProgressToken, other.ProgressToken)
	return
}

func (s *Session) preInit(msg *Message) (bool, error) {
	if msg.Method == "initialize" {
		var init InitializeRequest
		if err := json.Unmarshal(msg.Params, &init); err != nil {
			return false, fmt.Errorf("failed to unmarshal initialize request: %w", err)
		}
		s.InitializeRequest = init
		return true, nil
	}

	return false, nil
}

func (s *Session) postInit(msg *Message) error {
	if len(msg.Result) == 0 {
		return nil
	}
	var init InitializeResult
	if err := json.Unmarshal(msg.Result, &init); err != nil {
		return fmt.Errorf("failed to unmarshal initialize result: %w", err)
	}
	s.InitializeResult = init
	return nil
}

func (s *Session) marshalResponse(m Message, out any) error {
	if mOut, ok := out.(*Message); ok {
		*mOut = m
		return nil
	}
	if m.Error != nil {
		return fmt.Errorf("error from server: %w", m.Error)
	}
	if m.Result == nil {
		return ErrNoResult
	}
	if err := json.Unmarshal(m.Result, out); err != nil {
		return fmt.Errorf("failed to unmarshal result: %w", err)
	}
	return nil
}

func (s *Session) toRequest(method string, in any, opt ExchangeOption) (*Message, error) {
	req, ok := in.(*Message)
	if !ok {
		data, err := json.Marshal(in)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request: %w", err)
		}
		req = &Message{
			Method: method,
			Params: data,
		}
	}

	if req.ID == nil || req.ID == "" || req.ID == 0 || req.ID == 0.0 {
		req.ID = nextMessageID()
	}
	if opt.ProgressToken != nil {
		if err := req.SetProgressToken(opt.ProgressToken); err != nil {
			return nil, fmt.Errorf("failed to set progress token: %w", err)
		}
	}

	return req, nil
}

func getMessageName(req *Message) string {
	var name string
	switch req.Method {
	case "resources/read", "resources/subscribe", "resources/unsubscribe":
		_ = json.Unmarshal(req.Params, &struct {
			Uri *string `json:"uri,omitempty"`
		}{
			Uri: &name,
		})
	case "tools/call", "prompts/get":
		_ = json.Unmarshal(req.Params, &struct {
			Name *string `json:"name,omitempty"`
		}{
			Name: &name,
		})
	default:
	}
	return name
}

func (s *Session) callAllHooks(ctx context.Context, req *Message, direction string) (*Message, error) {
	var (
		hooks    = s.hooks
		name     = getMessageName(req)
		auditLog = AuditLogFromContext(ctx)
		errs     []error
	)
	if len(hooks) == 0 {
		ctxServer := MCPServerConfigFromContext(ctx)
		if len(ctxServer.Hooks) > 0 {
			hooks = ctxServer.Hooks
			ctx = WithMCPServerConfig(ctx, Server{})
		}
	}

	params := map[string]string{
		"name":        name,
		"direction":   direction,
		"callOnError": fmt.Sprintf("%v", req.Error != nil),
		"method":      req.Method,
	}

	// errs will be caught in callback, we don't need to handle the return err
	hookResponse, _ := InvokeHooks(ctx, s.HookRunner, hooks, &SessionMessageHook{
		Accept:  true,
		Message: req,
	}, req.Method, params, func(hook HookMapping, hookResponse SessionMessageHook, err error) SessionMessageHook {
		if err != nil {
			errs = append(errs, fmt.Errorf("failed to run hook %s: %w", hook.Name, err))
			return hookResponse
		}

		if auditLog != nil {
			status := "ok"
			if !hookResponse.Accept {
				status = "rejected"
			}
			auditLog.WebhookStatuses = append(auditLog.WebhookStatuses, auditlogs.MCPWebhookStatus{
				Type:    direction,
				Method:  req.Method,
				Name:    hook.Name,
				Status:  status,
				Message: hookResponse.Reason,
			})
		}

		if !hookResponse.Accept {
			errs = append(errs, fmt.Errorf("hook %s rejected message: %s", hook.Name, hookResponse.Reason))
		}

		// Use the hook response message if set, otherwise use the last value we have
		if hookResponse.Message == nil {
			hookResponse.Message = req
		} else {
			req = hookResponse.Message
		}
		return hookResponse
	})

	return hookResponse.Message, errors.Join(errs...)
}

func (s *Session) Exchange(ctx context.Context, method string, in, out any, opts ...ExchangeOption) (err error) {
	opt := complete.Complete(opts...)
	var (
		req        *Message
		respResult json.RawMessage
		respError  *RPCError
	)
	req, err = s.toRequest(method, in, opt)
	if err != nil {
		return err
	}

	defer func() {
		tempReq := *req
		tempReq.Result = respResult
		tempReq.Error = respError
		if err != nil && respError == nil {
			tempReq.Error = ErrRPCUnknown.WithMessage("failed to call %s [%s]: %v", req.Method, getMessageName(req), err)
		}
		if _, hooksErr := s.callAllHooks(ctx, &tempReq, "response"); hooksErr != nil && err == nil {
			err = fmt.Errorf("failed to call \"response\" hooks: %w", hooksErr)
		}
	}()

	ch := s.pendingRequest.WaitFor(req.ID)
	defer s.pendingRequest.Done(req.ID)

	isInit, err := s.preInit(req)
	if err != nil {
		return err
	}

	errChan := make(chan error, 1)

	go func() {
		defer close(errChan)

		if err := s.Send(ctx, *req); err != nil {
			errChan <- fmt.Errorf("failed to send request: %w", err)
		}
	}()

	for {
		select {
		case <-ctx.Done():
			// Check if this was a client-initiated cancellation and forward it downstream
			cause := context.Cause(ctx)
			if cancelErr, ok := errors.AsType[*RequestCancelledError](cause); ok {
				// Forward cancellation notification to the downstream server
				// Use the session context since the current context is cancelled
				_ = s.SendPayload(s.Context(), "notifications/cancelled", CancelledNotification{
					RequestID: req.ID,
					Reason:    cancelErr.Reason,
				})

				return cause
			}
			return ctx.Err()
		case err = <-errChan:
			if err != nil {
				return err
			}
			// If the error is nil, then the send call was successful.
			// Set the error channel to nil so that this case always blocks.
			errChan = nil
		case m := <-ch:
			if isInit {
				if err := s.postInit(&m); err != nil {
					return fmt.Errorf("failed to post init: %w", err)
				}
			}
			respResult = m.Result
			respError = m.Error
			return s.marshalResponse(m, out)
		}
	}
}

func (s *Session) onWire(ctx context.Context, message Message) {
	message.Session = s
	if s.pendingRequest.Notify(message) {
		return
	}
	s.handler.OnMessage(WithSession(ctx, s), message)
}

func NewEmptySession(ctx context.Context) *Session {
	s := &Session{}
	s.ctx, s.cancel = context.WithCancelCause(WithSession(ctx, s))
	return s
}

func newSession(ctx context.Context, wire Wire, handler MessageHandler, session *SessionState, r HookRunner, hooks Hooks, parentSession *Session) (*Session, error) {
	s := &Session{
		wire:       wire,
		handler:    handler,
		HookRunner: r,
		hooks:      hooks,
		Parent:     parentSession,
	}
	if session != nil {
		s.InitializeRequest = session.InitializeRequest
		s.InitializeResult = session.InitializeResult
	}
	withSession := WithSession(ctx, s)
	s.ctx, s.cancel = context.WithCancelCause(withSession)

	if err := wire.Start(s.ctx, s.onWire); err != nil {
		return nil, err
	}

	go func() {
		wire.Wait()
		s.Close(false)
	}()

	return s, nil
}

type Serializable interface {
	Serialize() (any, error)
}

type Deserializable interface {
	Deserialize(v any) (any, error)
}

type Closer interface {
	Close() error
}

type SavedString string

func (s SavedString) Serialize() (any, error) {
	return s, nil
}
