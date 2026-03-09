package agents

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func (a *Agents) toolCalls(ctx context.Context, run *types.Execution, opts []types.CompletionOptions) {
	for _, output := range run.Response.Output.Items {
		functionCall := output.ToolCall

		if functionCall == nil || run.ToolOutputs[functionCall.CallID].Done {
			continue
		}

		targetServer, ok := run.ToolToMCPServer[functionCall.Name]
		if !ok {
			err := fmt.Errorf("can not map tool %s to a MCP server", functionCall.Name)

			tcResult := &types.ToolCallResult{
				CallID: functionCall.CallID,
				Output: types.CallResult{
					Content: []mcp.Content{
						{
							Type: "text",
							Text: err.Error(),
						},
					},
				},
			}

			opt := complete.Complete(opts...)
			if opt.ProgressToken != nil {
				// Send a notification so that UI updates.
				_ = mcp.SessionFromContext(ctx).SendPayload(ctx, "notifications/progress", mcp.NotificationProgressRequest{
					ProgressToken: opt.ProgressToken,
					Meta: map[string]any{
						types.CompletionProgressMetaKey: types.CompletionProgress{
							MessageID: run.Response.Output.ID,
							Item: types.CompletionItem{
								ID:             output.ID,
								ToolCall:       functionCall,
								ToolCallResult: tcResult,
							},
						},
					},
				})
			}

			callOutput := &types.Message{
				Role: "user",
				Items: []types.CompletionItem{
					{
						Partial:        true,
						ID:             output.ID,
						ToolCallResult: tcResult,
					},
				},
			}

			if run.ToolOutputs == nil {
				run.ToolOutputs = make(map[string]types.ToolOutput)
			}

			run.ToolOutputs[functionCall.CallID] = types.ToolOutput{
				Output: *callOutput,
				Done:   true,
			}

			return
		}

		if targetServer.Target.External {
			// Handled externally, so terminate the run waiting for the client
			run.Done = true
			continue
		}

		callOutput, err := a.invoke(ctx, targetServer, tools.ToolCallInvocation{
			MessageID: run.Response.Output.ID,
			ItemID:    output.ID,
			ToolCall:  *functionCall,
		}, opts)
		cancelCause := context.Cause(mcp.UserContext(ctx))
		if err != nil || cancelCause != nil {
			// Check if this was a client-initiated cancellation
			cancelErr, ok := errors.AsType[*mcp.RequestCancelledError](cancelCause)
			if ok && cancelErr != nil {
				err = cancelErr
				// Preserve what we have and stop processing further tool calls
				run.Done = true
			} else {
				err = fmt.Errorf("failed to invoke tool %s on MCP server %s: %w", functionCall.Name, targetServer.MCPServer, err)
			}

			if callOutput == nil ||
				len(callOutput.Items) == 0 ||
				callOutput.Items[0].ToolCallResult == nil ||
				len(callOutput.Items[0].ToolCallResult.Output.Content) == 0 {
				callOutput = &types.Message{
					Role: "user",
					Items: []types.CompletionItem{
						{
							ID: output.ID,
							ToolCallResult: &types.ToolCallResult{
								CallID: functionCall.CallID,
								Output: types.CallResult{
									Content: []mcp.Content{
										{
											Type: "text",
											Text: err.Error(),
										},
									},
								},
							},
						},
					},
				}
			}
		}

		callOutput = truncateToolResult(ctx, functionCall.Name, functionCall.CallID, callOutput)

		if run.ToolOutputs == nil {
			run.ToolOutputs = make(map[string]types.ToolOutput)
		}

		run.ToolOutputs[functionCall.CallID] = types.ToolOutput{
			Output: *callOutput,
			Done:   true,
		}
	}

	if len(run.ToolOutputs) == 0 {
		run.Done = true
	}
}

func (a *Agents) invoke(ctx context.Context, target types.TargetMapping[types.TargetTool], funcCall tools.ToolCallInvocation, opts []types.CompletionOptions) (*types.Message, error) {
	var data map[string]any

	if funcCall.ToolCall.Arguments != "" {
		data = make(map[string]any)
		if err := json.Unmarshal([]byte(funcCall.ToolCall.Arguments), &data); err != nil {
			return nil, fmt.Errorf("failed to unmarshal function call arguments: %w", err)
		}
	}

	response, err := a.registry.Call(ctx, target.MCPServer, target.TargetName, data, tools.CallOptions{
		ProgressToken:      complete.Complete(opts...).ProgressToken,
		ToolCallInvocation: &funcCall,
	})
	if err != nil {
		response = &types.CallResult{
			Content: []mcp.Content{
				{
					Type: "text",
					Text: fmt.Sprintf("Error calling %s: %v", target.TargetName, err),
				},
			},
			IsError: true,
		}
	}
	return &types.Message{
		Role: "user",
		Items: []types.CompletionItem{
			{
				ToolCallResult: &types.ToolCallResult{
					CallID: funcCall.ToolCall.CallID,
					Output: *response,
				},
			},
		},
	}, nil
}
