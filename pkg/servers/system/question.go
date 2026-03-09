package system

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/servers/agent"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

type QuestionOption struct {
	Label       string `json:"label"`
	Description string `json:"description,omitempty"`
}

type Question struct {
	Question string           `json:"question"`
	Header   string           `json:"header"`
	Multiple bool             `json:"multiple,omitempty"`
	Options  []QuestionOption `json:"options"`
}

type QuestionParams struct {
	Questions []Question `json:"questions"`
}

func (s *Server) question(ctx context.Context, params QuestionParams) (string, error) {
	if len(params.Questions) == 0 {
		return "", mcp.ErrRPCInvalidParams.WithMessage("at least one question is required")
	}

	for i, q := range params.Questions {
		if q.Question == "" {
			return "", mcp.ErrRPCInvalidParams.WithMessage("question %d: question text is required", i+1)
		}
		if q.Header == "" {
			return "", mcp.ErrRPCInvalidParams.WithMessage("question %d: header is required", i+1)
		}
		if len(q.Options) == 0 {
			return "", mcp.ErrRPCInvalidParams.WithMessage("question %d: at least one option is required", i+1)
		}
		for j, opt := range q.Options {
			if opt.Label == "" {
				return "", mcp.ErrRPCInvalidParams.WithMessage("question %d, option %d: label is required", i+1, j+1)
			}
		}
	}

	// Get root session for sending elicitation to the UI
	session := mcp.SessionFromContext(ctx).Root()
	if session == nil {
		return "", fmt.Errorf("no session found in context")
	}

	// Build _meta with questions data
	meta := map[string]any{
		types.MetaPrefix + "question": params.Questions,
	}
	metaBytes, err := json.Marshal(meta)
	if err != nil {
		return "", fmt.Errorf("failed to marshal question metadata: %w", err)
	}

	// Build PrimitiveSchema with one string property per question
	properties := make(map[string]mcp.PrimitiveProperty, len(params.Questions))
	for i, q := range params.Questions {
		key := fmt.Sprintf("q%d", i)
		properties[key] = mcp.PrimitiveProperty{
			Type:  "string",
			Title: q.Header,
		}
	}

	// Build and send elicitation request
	elicit := mcp.ElicitRequest{
		Message: buildQuestionMessage(params.Questions),
		RequestedSchema: mcp.PrimitiveSchema{
			Type:       "object",
			Properties: properties,
		},
		Meta: metaBytes,
	}

	var result mcp.ElicitResult
	if err := agent.ExchangeElicitation(ctx, session, elicit, &result); err != nil {
		return "", fmt.Errorf("failed to send question elicitation: %w", err)
	}

	switch result.Action {
	case "accept":
		return formatQuestionAnswers(params.Questions, result.Content), nil
	case "decline":
		return "The user declined to answer the questions.", nil
	default:
		return "The user canceled the questions.", nil
	}
}

func buildQuestionMessage(questions []Question) string {
	var sb strings.Builder
	sb.WriteString("Please answer the following questions:\n\n")
	for i, q := range questions {
		fmt.Fprintf(&sb, "%d. %s\n", i+1, q.Question)
	}
	return sb.String()
}

func formatQuestionAnswers(questions []Question, content map[string]any) string {
	var sb strings.Builder
	for i, q := range questions {
		key := fmt.Sprintf("q%d", i)
		rawVal, ok := content[key]
		if !ok {
			fmt.Fprintf(&sb, "%s: (skipped)\n", q.Header)
			continue
		}
		rawStr, _ := rawVal.(string)
		var answers []string
		if err := json.Unmarshal([]byte(rawStr), &answers); err != nil {
			// If not a JSON array, treat as plain string
			answers = []string{rawStr}
		}
		fmt.Fprintf(&sb, "%s: %s\n", q.Header, strings.Join(answers, ", "))
	}
	return strings.TrimSpace(sb.String())
}
