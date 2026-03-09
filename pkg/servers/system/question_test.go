package system

import (
	"context"
	"strings"
	"testing"
)

func TestQuestionValidation(t *testing.T) {
	s := &Server{}

	tests := []struct {
		name    string
		params  QuestionParams
		wantErr string
	}{
		{
			name:    "empty questions",
			params:  QuestionParams{Questions: []Question{}},
			wantErr: "at least one question",
		},
		{
			name: "missing question text",
			params: QuestionParams{Questions: []Question{
				{Question: "", Header: "H", Options: []QuestionOption{{Label: "A"}}},
			}},
			wantErr: "question text is required",
		},
		{
			name: "missing header",
			params: QuestionParams{Questions: []Question{
				{Question: "Q?", Header: "", Options: []QuestionOption{{Label: "A"}}},
			}},
			wantErr: "header is required",
		},
		{
			name: "no options",
			params: QuestionParams{Questions: []Question{
				{Question: "Q?", Header: "H", Options: []QuestionOption{}},
			}},
			wantErr: "at least one option",
		},
		{
			name: "missing option label",
			params: QuestionParams{Questions: []Question{
				{Question: "Q?", Header: "H", Options: []QuestionOption{{Label: ""}}},
			}},
			wantErr: "label is required",
		},
		{
			name: "valid params but no session",
			params: QuestionParams{Questions: []Question{
				{Question: "Q?", Header: "H", Options: []QuestionOption{{Label: "A"}}},
			}},
			wantErr: "no session found",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := s.question(context.Background(), tt.params)
			if err == nil {
				t.Fatal("expected error, got nil")
			}
			if got := err.Error(); !strings.Contains(got, tt.wantErr) {
				t.Errorf("error %q does not contain %q", got, tt.wantErr)
			}
		})
	}
}

func TestBuildQuestionMessage(t *testing.T) {
	tests := []struct {
		name      string
		questions []Question
		want      string
	}{
		{
			name: "single question",
			questions: []Question{
				{Question: "What language?"},
			},
			want: "Please answer the following questions:\n\n1. What language?\n",
		},
		{
			name: "multiple questions",
			questions: []Question{
				{Question: "What language?"},
				{Question: "What framework?"},
				{Question: "What database?"},
			},
			want: "Please answer the following questions:\n\n1. What language?\n2. What framework?\n3. What database?\n",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := buildQuestionMessage(tt.questions)
			if got != tt.want {
				t.Errorf("got %q, want %q", got, tt.want)
			}
		})
	}
}

func TestFormatQuestionAnswers(t *testing.T) {
	tests := []struct {
		name      string
		questions []Question
		content   map[string]any
		want      string
	}{
		{
			name:      "single answer",
			questions: []Question{{Header: "Language"}},
			content:   map[string]any{"q0": `["Go"]`},
			want:      "Language: Go",
		},
		{
			name:      "multiple selections",
			questions: []Question{{Header: "Languages"}},
			content:   map[string]any{"q0": `["Go","Python"]`},
			want:      "Languages: Go, Python",
		},
		{
			name:      "plain string answer",
			questions: []Question{{Header: "Name"}},
			content:   map[string]any{"q0": "custom text"},
			want:      "Name: custom text",
		},
		{
			name:      "skipped question",
			questions: []Question{{Header: "Language"}},
			content:   map[string]any{},
			want:      "Language: (skipped)",
		},
		{
			name: "mixed answered and skipped",
			questions: []Question{
				{Header: "Language"},
				{Header: "Framework"},
				{Header: "Database"},
			},
			content: map[string]any{
				"q0": `["Go"]`,
				"q2": `["PostgreSQL"]`,
			},
			want: "Language: Go\nFramework: (skipped)\nDatabase: PostgreSQL",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := formatQuestionAnswers(tt.questions, tt.content)
			if got != tt.want {
				t.Errorf("got %q, want %q", got, tt.want)
			}
		})
	}
}
