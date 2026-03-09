package config

import (
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

var UI = types.Config{
	Agents: map[string]types.Agent{
		"nanobot.summary": {
			HookAgent: types.HookAgent{
				Name:  "nanobot.summary",
				Model: "mini",
				Chat:  new(bool),
				Instructions: types.DynamicInstructions{
					Instructions: `- you will generate a short title based on the first message a user begins a conversation with
- ensure it is not more than 80 characters long
- the title should be a summary of the user's message
- do not use quotes or colons
- DO NOT MAKE ANY TOOL CALLS, this is purely for generating a title`,
				},
				Permissions: types.DenyAllPermissions(),
			},
		},
	},
	Publish: types.Publish{
		MCPServers: []string{"nanobot.meta", "nanobot.workflows"},
		Tools:      []string{"nanobot.workflow-tools/deleteWorkflow", "nanobot.system/uploadFile", "nanobot.system/deleteFile"},
		Resources:  []string{"nanobot.system"},
	},
	MCPServers: map[string]mcp.Server{
		"nanobot.meta":           {},
		"nanobot.workflows":      {},
		"nanobot.workflow-tools": {},
		"nanobot.system":         {},
	},
}
