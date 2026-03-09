package auditlogs

import (
	"encoding/json"
	"strings"
	"time"
)

// MCPAuditLog represents an audit log entry for MCP API calls
type MCPAuditLog struct {
	// Metadata is additional information about this server that a user can provide for audit log tracking purposes.
	// For example Obot uses this to track catalog information.
	Metadata         map[string]string  `json:"metadata,omitempty"`
	CreatedAt        time.Time          `json:"createdAt"`
	Subject          string             `json:"subject"`
	APIKey           string             `json:"apiKey,omitempty"`
	ClientName       string             `json:"clientName"`
	ClientVersion    string             `json:"clientVersion"`
	ClientIP         string             `json:"clientIP"`
	CallType         string             `json:"callType"`
	CallIdentifier   string             `json:"callIdentifier,omitempty"`
	RequestBody      json.RawMessage    `json:"requestBody,omitempty"`
	ResponseBody     json.RawMessage    `json:"responseBody,omitempty"`
	ResponseStatus   int                `json:"responseStatus"`
	Error            string             `json:"error,omitempty"`
	ProcessingTimeMs int64              `json:"processingTimeMs"`
	SessionID        string             `json:"sessionID,omitempty"`
	WebhookStatuses  []MCPWebhookStatus `json:"webhookStatuses,omitempty"`

	// Additional metadata
	RequestID       string          `json:"requestID,omitempty"`
	UserAgent       string          `json:"userAgent,omitempty"`
	RequestHeaders  json.RawMessage `json:"requestHeaders,omitempty"`
	ResponseHeaders json.RawMessage `json:"responseHeaders,omitempty"`
}

type MCPWebhookStatus struct {
	Type    string `json:"type,omitempty"`
	Method  string `json:"method,omitempty"`
	Name    string `json:"name"`
	Status  string `json:"status"`
	Message string `json:"message,omitempty"`
}

// RedactAPIKey redacts an API key, keeping everything to the third hyphen, or the first 12 characters, whichever is longer.
// If the API key is less than 20 characters, it compares the third hyphen prefix to the first half and returns whichever is longer.
func RedactAPIKey(apiKey string) string {
	if len(apiKey) < 2 {
		return ""
	}

	parts := strings.SplitAfterN(apiKey, "-", 4)
	prefix := strings.Join(parts[:min(3, len(parts))], "")

	if len(apiKey) < 20 {
		half := apiKey[:len(apiKey)/2]
		if len(parts) >= 4 && len(prefix) > len(half) {
			return prefix
		}
		return half
	}

	if len(parts) < 4 || len(prefix) < 12 {
		return apiKey[:12]
	}
	return prefix
}
