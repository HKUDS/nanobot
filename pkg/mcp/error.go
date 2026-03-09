package mcp

import "fmt"

type AuthRequiredErr struct {
	ProtectedResourceValue string
	Err                    error
}

func (e AuthRequiredErr) Error() string {
	return fmt.Sprintf("authentication required: %v", e.Err)
}

type SessionNotFoundErr struct {
	SessionID string
	Err       error
}

func (e SessionNotFoundErr) Error() string {
	return fmt.Sprintf("session %s not found: %v", e.SessionID, e.Err)
}
