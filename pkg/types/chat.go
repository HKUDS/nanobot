package types

import (
	"encoding/json"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

const (
	AgentTool             = "chat-with-"
	AgentToolDescription  = "Chat with the agent"
	AttachmentMetaKey     = "ai.nanobot.meta/attachment"
	SkipTruncationMetaKey = "ai.nanobot.meta/skip-truncation"
)

var ChatInputSchema = []byte(`{
  "type": "object",
  "required": ["prompt"],
  "properties": {
    "prompt": {
  	  "description": "The input prompt",
  	  "type": "string"
    },
    "attachments": {
	  "type": "array",
	  "items": {
	    "description": "An attachment to the prompt (optional)",
	    "type": "object",
	    "required": ["url"],
	    "properties": {
	      "name": {
	        "description": "The name of the resource, often the filename",
	        "type": "string"
	      },
	      "url": {
	        "description": "The URL of the attachment or data URI",
	        "type": "string"
	      },
	      "mimeType": {
	        "description": "The mime type of the content reference by the URL",
	        "type": "string"
	      }
	    }
	  }
    }
  }
}`)

type SampleCallRequest struct {
	Prompt      string       `json:"prompt"`
	Attachments []Attachment `json:"attachments,omitempty"`
}

type SampleConfirmRequest struct {
	ID     string `json:"id"`
	Accept bool   `json:"accept"`
}

type Attachment struct {
	Name     string `json:"name,omitempty"`
	URL      string `json:"url"`
	MimeType string `json:"mimeType,omitempty"`
}

func (a *Attachment) UnmarshalJSON(data []byte) error {
	if len(data) > 0 && data[0] == '"' {
		var url string
		if err := json.Unmarshal(data, &url); err != nil {
			return err
		}
		a.URL = url
		return nil
	}
	type Alias Attachment
	return json.Unmarshal(data, (*Alias)(a))
}

type ChatList struct {
	Chats []Chat `json:"chats"`
}

type Chat struct {
	ID           string    `json:"id"`
	Title        string    `json:"title"`
	Created      time.Time `json:"created"`
	ReadOnly     bool      `json:"readonly,omitempty"`
	WorkflowURIs []string  `json:"workflowURIs,omitempty"`
}

type AgentList struct {
	Agents []AgentDisplay `json:"agents"`
}

type AgentDisplay struct {
	ID              string   `json:"id"`
	Name            string   `json:"name"`
	ShortName       string   `json:"shortName"`
	Description     string   `json:"description"`
	Icon            string   `json:"icon"`
	IconDark        string   `json:"iconDark"`
	StarterMessages []string `json:"starterMessages"`
	Base            bool     `json:"base"`
	Current         bool     `json:"current"`
}

type Workspace struct {
	ID         string                 `json:"id"`
	Name       string                 `json:"name"`
	Order      int                    `json:"order"`
	Color      string                 `json:"color,omitempty"`
	Icons      []mcp.Icon             `json:"icons,omitempty"`
	Attributes map[string]interface{} `json:"attributes,omitempty"`
}
