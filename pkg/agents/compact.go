package agents

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
)

const (
	compactionThreshold      = 0.835
	compactionSummaryMetaKey = "ai.nanobot.meta/compaction-summary"
	defaultContextWindow     = 200_000
)

// getContextWindowSize returns the context window size for the given model.
// If configOverride is > 0, it is used directly. Otherwise, defaults to 200k.
func getContextWindowSize(configOverride int) int {
	if configOverride > 0 {
		return configOverride
	}
	return defaultContextWindow
}

// shouldCompact returns true if the estimated token count of the request
// exceeds the compaction threshold of the context window.
func shouldCompact(req types.CompletionRequest, contextWindowSize int) bool {
	if contextWindowSize <= 0 {
		return false
	}

	estimated := estimateTokens(req.Input, req.SystemPrompt, req.Tools)
	threshold := int(float64(contextWindowSize) * compactionThreshold)
	return estimated > threshold
}

// IsCompactionSummary checks whether a message is a compaction summary
// by looking for the compaction summary meta key.
func IsCompactionSummary(msg types.Message) bool {
	if len(msg.Items) == 0 {
		return false
	}
	item := msg.Items[0]
	if item.Content == nil || item.Content.Meta == nil {
		return false
	}
	_, ok := item.Content.Meta[compactionSummaryMetaKey]
	return ok
}

// splitHistoryAndNewInput separates the full populated input into history (messages
// from previous turns) and new input (messages from the current request).
// It finds the boundary by matching the first message ID from currentRequestInput.
func splitHistoryAndNewInput(fullInput, currentRequestInput []types.Message) (history, newInput []types.Message) {
	if len(currentRequestInput) == 0 {
		return fullInput, nil
	}

	firstNewID := currentRequestInput[0].ID
	for i, msg := range fullInput {
		if msg.ID == firstNewID {
			return fullInput[:i], fullInput[i:]
		}
	}

	// If we can't find the boundary, treat everything as history
	return fullInput, nil
}

type compactResult struct {
	compactedInput   []types.Message
	archivedMessages []types.Message
}

// compact performs conversation compaction by summarizing history messages
// into a condensed summary, allowing the conversation to continue within
// the context window limits.
//
// On re-compaction, only the messages since the previous summary are summarized
// (with the previous summary included as context). This keeps the summarization
// input bounded rather than growing with the full conversation.
func (a *Agents) compact(ctx context.Context, req types.CompletionRequest, currentRequestInput []types.Message, previousCompacted []types.Message) (*compactResult, error) {
	history, newInput := splitHistoryAndNewInput(req.Input, currentRequestInput)

	// Split history into: messages before/including the previous summary, and messages after it.
	// We only need to summarize the messages after the previous summary, using the summary as context.
	var previousSummaryText string
	var sinceLastSummary []types.Message
	lastSummaryIdx := -1
	for i, msg := range history {
		if IsCompactionSummary(msg) {
			lastSummaryIdx = i
			if len(msg.Items) > 0 && msg.Items[0].Content != nil {
				previousSummaryText = msg.Items[0].Content.Text
			}
		}
	}
	if lastSummaryIdx >= 0 {
		sinceLastSummary = history[lastSummaryIdx+1:]
	} else {
		sinceLastSummary = history
	}

	// Build summarization transcript from only the messages since the last summary
	transcript := buildTranscript(sinceLastSummary)

	var summaryPrompt string
	if previousSummaryText != "" {
		summaryPrompt = buildRecompactionPrompt(previousSummaryText, transcript)
	} else {
		summaryPrompt = buildInitialCompactionPrompt(transcript)
	}

	summaryReq := types.CompletionRequest{
		Model: req.Model,
		Input: []types.Message{
			{
				ID:   uuid.String(),
				Role: "user",
				Items: []types.CompletionItem{
					{
						ID: uuid.String(),
						Content: &mcp.Content{
							Type: "text",
							Text: summaryPrompt,
						},
					},
				},
			},
		},
	}

	resp, err := a.completer.Complete(ctx, summaryReq)
	if err != nil {
		return nil, fmt.Errorf("compaction summarization failed: %w", err)
	}

	// Extract summary text from response
	summaryText := extractTextFromResponse(resp)
	if summaryText == "" {
		return nil, fmt.Errorf("compaction produced empty summary")
	}

	// Create summary message with compaction metadata
	now := time.Now()
	summaryMessage := types.Message{
		ID:      "compaction-summary-" + uuid.String(),
		Created: &now,
		Role:    "user",
		Items: []types.CompletionItem{
			{
				ID: uuid.String(),
				Content: &mcp.Content{
					Type: "text",
					Text: buildCompactionCarryForwardMessage(summaryText),
					Meta: map[string]any{
						compactionSummaryMetaKey: true,
					},
				},
			},
		},
	}

	// Build the compacted input: summary + new user messages
	compactedInput := []types.Message{summaryMessage}
	compactedInput = append(compactedInput, newInput...)

	// Build archived messages: previous compacted + all history from this compaction (including old summaries)
	archivedMessages := make([]types.Message, 0, len(previousCompacted)+len(history))
	archivedMessages = append(archivedMessages, previousCompacted...)
	archivedMessages = append(archivedMessages, history...)

	return &compactResult{
		compactedInput:   compactedInput,
		archivedMessages: archivedMessages,
	}, nil
}

// buildTranscript creates a text representation of conversation messages
// suitable for summarization by an LLM.
func buildTranscript(messages []types.Message) string {
	var sb strings.Builder

	for _, msg := range messages {
		role := msg.Role
		if role == "" {
			role = "unknown"
		}

		for _, item := range msg.Items {
			if item.Content != nil && item.Content.Text != "" {
				fmt.Fprintf(&sb, "[%s]: %s\n", role, item.Content.Text)
			}
			if item.ToolCall != nil {
				fmt.Fprintf(&sb, "[%s] (tool call: %s): %s\n", role, item.ToolCall.Name, item.ToolCall.Arguments)
			}
			if item.ToolCallResult != nil {
				for _, c := range item.ToolCallResult.Output.Content {
					if c.Text != "" {
						// Truncate very long tool results in the transcript
						text := c.Text
						if len(text) > 5000 {
							text = text[:5000] + "... [truncated]"
						}
						fmt.Fprintf(&sb, "[tool result]: %s\n", text)
					}
					if c.Type == "image" {
						fmt.Fprintln(&sb, "[tool result]: [image data omitted]")
					}
				}
			}
		}
	}

	return sb.String()
}

// extractTextFromResponse extracts the text content from a completion response.
func extractTextFromResponse(resp *types.CompletionResponse) string {
	if resp == nil {
		return ""
	}

	var texts []string
	for _, item := range resp.Output.Items {
		if item.Content != nil && item.Content.Text != "" {
			texts = append(texts, item.Content.Text)
		}
	}
	return strings.Join(texts, "\n")
}

func buildInitialCompactionPrompt(transcript string) string {
	return fmt.Sprintf(`You are a helpful AI assistant tasked with summarizing conversations for handoff.

Provide a detailed but concise summary that will help another general-purpose assistant continue the conversation correctly.
Focus on:
- What has already been done
- What is currently in progress
- What should happen next
- Key user goals, constraints, preferences, and instructions that must persist
- Important decisions, facts, and context needed to avoid repeating work

When constructing the summary, use this template:
## Goal

[What the user is trying to accomplish]

## Key Instructions & Preferences

- [Important constraints, preferences, or requirements]

## What Happened

[Key actions, decisions, and notable outcomes so far]

## Current State

[What is complete, what is in progress, and any known blockers]

## Next Steps

- [The next concrete actions the assistant should take]

## Open Questions / Risks

- [Any unresolved questions, ambiguities, or risks]

Do not answer questions from the transcript. Output only the summary.

--- CONVERSATION TRANSCRIPT ---
%s
--- END TRANSCRIPT ---
`, transcript)
}

func buildRecompactionPrompt(previousSummaryText, transcript string) string {
	return fmt.Sprintf(`You are a helpful AI assistant tasked with updating a conversation handoff summary.

You are given a previous summary plus new messages that occurred after that summary.
Create a single updated summary suitable for a general-purpose assistant to continue the conversation.

Merge rules:
- Treat the previous summary as prior context
- Integrate only the new information and status changes from the new messages
- Preserve unresolved tasks and open questions
- Remove or collapse duplicate details
- Keep completed items clearly marked as completed

Use this template:
## Goal

[What the user is trying to accomplish]

## Key Instructions & Preferences

- [Important constraints, preferences, or requirements]

## What Happened

[Key actions, decisions, and notable outcomes so far]

## Current State

[What is complete, what is in progress, and any known blockers]

## Next Steps

- [The next concrete actions the assistant should take]

## Open Questions / Risks

- [Any unresolved questions, ambiguities, or risks]

Do not answer questions from the transcript. Output only the updated summary.

--- PREVIOUS SUMMARY ---
%s
--- END PREVIOUS SUMMARY ---

--- NEW MESSAGES ---
%s
--- END NEW MESSAGES ---
`, previousSummaryText, transcript)
}

func buildCompactionCarryForwardMessage(summaryText string) string {
	return fmt.Sprintf("The conversation history was compacted to stay within context limits. Continue the conversation naturally using the summary below as working context. Do not mention this compaction unless the user asks.\n\n[Conversation Summary]\n%s", summaryText)
}
