package config

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"sigs.k8s.io/yaml"
)

func TestSchema(t *testing.T) {
	data, err := os.ReadFile("./schema.yaml")
	if err != nil {
		t.Fatalf("Failed to read schema file: %v", err)
	}

	schema := map[string]any{}
	if err := yaml.Unmarshal(data, &schema); err != nil {
		t.Fatalf("Failed to unmarshal schema: %v", err)
	}

	c := jsonschema.NewCompiler()
	if err := c.AddResource("schema.json", schema); err != nil {
		t.Fatalf("Failed to add resource to compiler: %v", err)
	}

	s, err := c.Compile("schema.json")
	if err != nil {
		t.Fatalf("Failed to compile schema: %v", err)
	}

	obj := map[string]any{}
	err = json.Unmarshal([]byte(`
{
	"workspaceId": "workspace123",
	"workspaceBaseUri": "https://example.com/workspaces/workspace123",
	"auth": {
		"oauthClientId": "clientid",
		"oauthClientSecret": "clientsecret",
		"oauthAuthorizeUrl": "http://localhost:8080/oauth/authorize",
		"oauthScopes": ["scope1", "scope2"],
		"oauthAuthorizationServerMetadata": {
			"authorizationEndpoint": "http://localhost:8080/oauth/authorize",
			"tokenEndpoint": "http://localhost:8080/oauth/token"
		},
		"encryptionKey": "encryptionkey"
	},
	"hooks": {
		"config": ["hook1.js", "hook2.js"],
		"request": "hook3.js",
		"response": ["hook4.js"]
	},
	"mcpServers": {
		"server1": {
			"command": "command1",
			"workdir": "/path/to/workdir",
			"args": ["arg1", "arg2"],
			"url": "http://example.com",
			"env": {
				"env1": "value1",
				"env2": "value2"
			},
			"image": "an image",
			"dockerfile": "Dockerfile content",
			"source": {
				"repo": ".",
				"tag": "latest",
				"commit": "abc123",
				"branch": "main",
				"subPath": "sub/path",
				"reference": "v1.0.0"
			},
			"unsandboxed": true,
			"ports": ["asdf", "fff"],
			"reversePorts": [123,234],
			"headers": {
				"header1": "value1"
			}
		}
	},
	"publish": {
		"name": "test",
		"version": "1.0.0",
		"entrypoint": "entrypoint1",
		"tools": "server1",
		"mcpServers": "server1",
		"instructions": "These are the instructions for the publish.",
		"introduction": "The introduction to the publish.",
		"resources": ["resource1", "resource2"],
		"resourceTemplates": ["resource1", "resource2"],
		"prompts": ["prompt1", "prompt2"]
	},
    "env": {
		"env2": "Short description of env2",
		"env1": {
			"default": "default value",
			"description": "This is the first environment.",
			"options": [ "option1", "option2" ],
			"optional": true,
			"sensitive": true,
			"useBearerToken": true
		}
    },
	"agents": {
		"agent1": {
			"mcpServers": "otherServer",
			"starterMessages": "Hi",
			"icon": "foo",
			"iconDark": "foo",
			"description": "This is the first agent.",
			"model": "a model",
			"tools": "atool",
			"reasoning": {
				"effort": "low",
				"summary": "detailed"
			},
			"prompts": ["prompt1", "prompt2"],
			"resources": ["prompt1", "prompt2"],
			"agents": "atool",
			"chat": true,
			"instructions": "These are the instructions for the agent.",
			"toolExtensions": {
				"tool1": {
					"extension1": "value1",
					"extension2": true
				}
			},
			"toolChoice": "tool1",
            "temperature": 0.7,
            "topP": 0.2,
			"output": {
				"name": "output1",
				"description": "This is the output schema for agent1.",
				"strict": false,
				"fields": {
					"field1": "description1",
					"field2": "description2",
					"field3": {
						"description": "description3",
						"fields": {
							"fields4": "description4",
							"fields5": "description5"
						}
					}
				}
			},
			"truncation": "auto",
			"maxTokens": 100,
			"aliases": ["alias1", "alias2"],
			"cost": 0.1,
			"speed": 0.3,
			"intelligence": 0.7
		},
		"agent2": {
			"threadName": "a different thread",
			"tools": ["tool1", "tool2"],
			"agents": ["tool1", "tool2"],
			"instructions": {
				"mcpServer": "aserver",
				"prompt": "aprompt",
				"args": {
					"key": "value"
				}
			}
		}
	},
	"prompts": {
		"prompt1": {
			"description": "a description",
			"template": "This is the template for prompt1.",
			"input": {
				"field1": "description1",
				"field2": {
					"description": "description2",
					"required": false
				}
			}
		}
	}
}`), &obj)
	if err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	err = s.Validate(obj)
	if err != nil {
		t.Fatalf("Failed to validate schema: %v", err)
	}
}
