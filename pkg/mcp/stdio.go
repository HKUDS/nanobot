package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	log2 "log"
	"log/slog"
	"os/exec"
	"strings"
	"sync"

	"github.com/nanobot-ai/nanobot/pkg/log"
)

type waiter struct {
	running chan struct{}
	closed  bool
	lock    sync.Mutex
}

func newWaiter() *waiter {
	return &waiter{
		running: make(chan struct{}),
	}
}

func (w *waiter) Wait() {
	<-w.running
}

func (w *waiter) Close() {
	w.lock.Lock()
	if !w.closed {
		w.closed = true
		close(w.running)
	}
	w.lock.Unlock()
}

type Stdio struct {
	stdout         io.Reader
	stdin          io.Writer
	cmd            *exec.Cmd
	closer         func()
	server         string
	pendingRequest PendingRequests
	waiter         *waiter
	writeLock      sync.Mutex
}

func (s *Stdio) Send(ctx context.Context, req Message) error {
	s.writeLock.Lock()
	defer s.writeLock.Unlock()

	data, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	if s.cmd != nil && (s.cmd.Process == nil || s.cmd.ProcessState != nil) {
		return fmt.Errorf("stdin is closed")
	}

	if slog.Default().Enabled(ctx, slog.LevelDebug) {
		slog.Debug("mcp stdio send",
			"server", s.server,
			"method", req.Method,
			"request_id", MessageIDString(req.ID),
			"call_identifier", getMessageName(&req))
	}

	log.Messages(ctx, s.server, true, data)
	_, err = s.stdin.Write(append(data, '\n'))
	return err
}

func (s *Stdio) SessionID() string {
	// Stdio does not have a session ID, return an empty string
	return ""
}

func (s *Stdio) Wait() {
	s.waiter.Wait()
}

func (s *Stdio) Close(bool) {
	s.closer()
	s.waiter.Close()
}

func (s *Stdio) Start(ctx context.Context, handler WireHandler) error {
	context.AfterFunc(ctx, func() {
		s.Close(false)
	})
	go func() {
		err := s.start(ctx, handler)
		if err != nil {
			log2.Fatal(err)
		}
	}()
	return nil
}

func (s *Stdio) start(ctx context.Context, handler WireHandler) error {
	defer s.Close(false)

	buf := bufio.NewScanner(s.stdout)
	buf.Buffer(make([]byte, 0, 1024), 10*1024*1024)
	for buf.Scan() {
		text := strings.TrimSpace(buf.Text())
		log.Messages(ctx, s.server, false, []byte(text))
		var msg Message
		if err := json.Unmarshal([]byte(text), &msg); err != nil {
			slog.Error("failed to unmarshal message", "error", err)
			continue
		}
		if slog.Default().Enabled(ctx, slog.LevelDebug) {
			slog.Debug("mcp stdio receive",
				"server", s.server,
				"method", msg.Method,
				"request_id", MessageIDString(msg.ID),
				"call_identifier", getMessageName(&msg))
		}
		go handler(ctx, msg)
	}
	return buf.Err()
}

func newStdioClient(ctx context.Context, roots func(context.Context) ([]Root, error), env map[string]string, serverName string, config Server, r *Runner) (*Stdio, error) {
	result, err := r.Stream(ctx, roots, env, serverName, config)
	if err != nil {
		return nil, fmt.Errorf("failed to create stream: %w", err)
	}

	s := NewStdio(serverName, result.cmd, result.Stdout, result.Stdin, result.Close)
	return s, nil
}

func NewStdio(server string, cmd *exec.Cmd, in io.Reader, out io.Writer, close func()) *Stdio {
	return &Stdio{
		server: server,
		cmd:    cmd,
		stdout: in,
		stdin:  out,
		closer: close,
		waiter: newWaiter(),
	}
}
