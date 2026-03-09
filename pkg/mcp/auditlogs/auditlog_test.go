package auditlogs

import "testing"

func TestRedactAPIKey(t *testing.T) {
	tests := []struct {
		name     string
		apiKey   string
		expected string
	}{
		{
			name:     "standard API key",
			apiKey:   "ok1-123-456-secretABC",
			expected: "ok1-123-456-",
		},
		{
			name:     "longer API key",
			apiKey:   "ok1-12345-67890-secret-with-dashes-and-more",
			expected: "ok1-12345-67890-",
		},
		{
			name:     "short key",
			apiKey:   "ab",
			expected: "a",
		},
		{
			name:     "single character",
			apiKey:   "a",
			expected: "",
		},
		{
			name:     "empty string",
			apiKey:   "",
			expected: "",
		},
		{
			name:     "four characters",
			apiKey:   "ok1-",
			expected: "ok",
		},
		{
			name:     "only two hyphens",
			apiKey:   "ok1-abc-defghijklmnop",
			expected: "ok1-abc-defg",
		},
		{
			name:     "no hyphens",
			apiKey:   "abcdefghijklmnopqrst",
			expected: "abcdefghijkl",
		},
		{
			name:     "exactly 12 characters",
			apiKey:   "exactly12chr",
			expected: "exactl",
		},
		{
			name:     "short prefix with three hyphens",
			apiKey:   "a-b-c-secretdata",
			expected: "a-b-c-se",
		},
		{
			name:     "many hyphens short segments",
			apiKey:   "a-b-c-d-e-f-g-h",
			expected: "a-b-c-d",
		},
		{
			name:     "eleven characters",
			apiKey:   "abcdefghijk",
			expected: "abcde",
		},
		{
			name:     "19 characters one hyphen",
			apiKey:   "prefix-secretsecret",
			expected: "prefix-se",
		},
		{
			name:     "prefix exactly 12 chars",
			apiKey:   "ok1-12345678-x-secret",
			expected: "ok1-12345678-x-",
		},
		{
			name:     "short key with three hyphens prefers prefix",
			apiKey:   "ok1-1-1-a",
			expected: "ok1-1-1-",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := RedactAPIKey(tt.apiKey)
			if result != tt.expected {
				t.Errorf("RedactAPIKey(%q) = %q, want %q", tt.apiKey, result, tt.expected)
			}
		})
	}
}
