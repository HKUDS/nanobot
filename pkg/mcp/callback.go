package mcp

import (
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync"

	"golang.org/x/oauth2"
)

type AuthURLHandler interface {
	HandleAuthURL(context.Context, string, string) (bool, error)
}

type CallbackHandler interface {
	AuthURLHandler
	NewState(context.Context, *oauth2.Config, string) (string, <-chan CallbackPayload, error)
}

type CallbackServer interface {
	http.Handler
	CallbackHandler
}

type CallbackPayload struct {
	Code             string `json:"code"`
	Error            string `json:"error"`
	ErrorDescription string `json:"error_description"`
}

type callbackHandler struct {
	AuthURLHandler
	lock  *sync.Mutex
	state map[string]callback
}

func NewCallbackServer(authURLHandler AuthURLHandler) CallbackServer {
	return &callbackHandler{
		lock:           new(sync.Mutex),
		state:          make(map[string]callback),
		AuthURLHandler: authURLHandler,
	}
}

func (s *callbackHandler) NewState(_ context.Context, conf *oauth2.Config, _ string) (string, <-chan CallbackPayload, error) {
	state := strings.ToLower(rand.Text())
	ch := make(chan CallbackPayload, 1)
	s.lock.Lock()
	s.state[state] = callback{
		conf: conf,
		ch:   ch,
	}
	s.lock.Unlock()
	return state, ch, nil
}

func (s *callbackHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	state := r.URL.Query().Get("state")
	slog.Info("oauth callback received", "has_state", state != "")

	s.lock.Lock()
	c, ok := s.state[state]
	delete(s.state, state)
	s.lock.Unlock()

	if !ok {
		slog.Warn("oauth callback rejected invalid state", "has_state", state != "")
		http.Error(w, "invalid state", http.StatusBadRequest)
		return
	}

	cb := CallbackPayload{
		Code:             r.URL.Query().Get("code"),
		Error:            r.URL.Query().Get("error"),
		ErrorDescription: r.URL.Query().Get("error_description"),
	}
	select {
	case c.ch <- cb:
		close(c.ch)
	default:
		if cb.Error != "" {
			slog.Warn("oauth callback reported error", "error", cb.Error, "description", cb.ErrorDescription)
			http.Error(w, fmt.Sprintf("error(%s): %s", cb.Error, cb.ErrorDescription), http.StatusBadRequest)
			return
		} else if cb.Code == "" {
			slog.Warn("oauth callback missing code")
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		tok, err := c.conf.Exchange(r.Context(), cb.Code, oauth2.VerifierOption(c.verifier))
		if err != nil {
			slog.Warn("oauth callback token exchange failed", "error", err)
			http.Error(w, fmt.Sprintf("error: %s", err.Error()), http.StatusBadRequest)
			return
		}
		slog.Info("oauth callback token exchange succeeded")

		// Set the token in the cookie and redirect.
		http.SetCookie(w, &http.Cookie{
			Name:     "nanobot-token",
			Value:    tok.AccessToken,
			Path:     "/",
			Secure:   r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https",
			HttpOnly: true,
		})
		http.Redirect(w, r, c.redirectURL, http.StatusFound)
		return
	}

	_, _ = w.Write([]byte("Success!!"))
}

type callback struct {
	conf        *oauth2.Config
	redirectURL string
	verifier    string
	ch          chan<- CallbackPayload
}
