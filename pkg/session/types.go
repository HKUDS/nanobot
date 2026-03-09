package session

import (
	"database/sql/driver"
	"encoding/json"
	"fmt"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"gorm.io/gorm"
)

type ConfigWrapper types.Config

func (c ConfigWrapper) Value() (driver.Value, error) {
	return json.Marshal(c)
}

func (c *ConfigWrapper) Scan(value any) error {
	return scan(value, c)
}

type Env map[string]string

func (e Env) Value() (driver.Value, error) {
	return json.Marshal(e)
}

func (e *Env) Scan(value any) error {
	return scan(value, e)
}

type State mcp.SessionState

func (m State) Value() (driver.Value, error) {
	return json.Marshal(m)
}

func (m *State) Scan(value any) error {
	return scan(value, m)
}

func scan(value any, obj any) error {
	if value == nil {
		return nil
	}
	if data, ok := value.([]byte); ok {
		return json.Unmarshal(data, obj)
	}
	if data, ok := value.(string); ok {
		return json.Unmarshal([]byte(data), obj)
	}
	return fmt.Errorf("cannot scan %T into %T", value, obj)
}

type Session struct {
	gorm.Model
	Type        string        `json:"type,omitempty"`
	SessionID   string        `json:"sessionId" gorm:"uniqueIndex;not null"`
	Description string        `json:"description,omitempty"`
	AccountID   string        `json:"accountId,omitempty"`
	State       State         `json:"state" gorm:"type:json"`
	Config      ConfigWrapper `json:"config,omitempty" gorm:"type:json"`
	Cwd         string        `json:"cwd,omitempty"`
}

// WorkflowRun records that a workflow was executed within a session.
type WorkflowRun struct {
	SessionID   string `json:"sessionId" gorm:"primaryKey;not null"`
	WorkflowURI string `json:"workflowURI" gorm:"primaryKey;not null"`
}

type Token struct {
	gorm.Model
	AccountID string `json:"accountID,omitempty"`
	URL       string `json:"url,omitempty"`
	Data      string `json:"data,omitempty"`
}
