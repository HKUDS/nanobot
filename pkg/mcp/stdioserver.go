package mcp

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
)

type StdioServer struct {
	MessageHandler MessageHandler
	stdio          *Stdio
	envProvider    func() (map[string]string, error)
}

func NewStdioServer(envProvider func() (map[string]string, error), handler MessageHandler) *StdioServer {
	return &StdioServer{
		envProvider:    envProvider,
		MessageHandler: handler,
	}
}

func (s *StdioServer) Wait() {
	if s.stdio != nil {
		s.stdio.Wait()
	}
}

func (s *StdioServer) Start(ctx context.Context, in io.ReadCloser, out io.WriteCloser) error {
	session, err := NewServerSession(ctx, s.MessageHandler)
	if err != nil {
		return fmt.Errorf("failed to create stdio session: %w", err)
	}

	s.stdio = NewStdio("proxy", nil, in, out, func() {})

	if err = s.stdio.Start(ctx, func(ctx context.Context, msg Message) {
		if slog.Default().Enabled(ctx, slog.LevelDebug) {
			slog.Debug("mcp stdio server received message",
				"method", msg.Method,
				"request_id", MessageIDString(msg.ID),
				"call_identifier", getMessageName(&msg))
		}

		if s.envProvider != nil {
			env, err := s.envProvider()
			if err != nil {
				slog.Error("failed to reload environment", "error", err)
			} else {
				session.session.SetEnv(env)
			}
		}

		resp, err := session.Exchange(ctx, msg)
		if errors.Is(err, ErrNoResponse) {
			return
		} else if err != nil {
			slog.Error("failed to exchange message", "error", err)
		}
		if err := s.stdio.Send(ctx, resp); err != nil {
			slog.Error("failed to send message in reply", "message_id", msg.ID, "error", err)
		}
	}); err != nil {
		return fmt.Errorf("failed to start stdio: %w", err)
	}

	go func() {
		s.stdio.Wait()
		session.Close(false)
	}()

	return nil
}
