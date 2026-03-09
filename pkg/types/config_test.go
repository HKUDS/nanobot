package types

import (
	"encoding/json"
	"reflect"
	"testing"

	"gopkg.in/yaml.v3"
)

func TestAgentPermissions_UnmarshalJSON(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected AgentPermissions
		wantErr  bool
	}{
		{
			name:  "empty object",
			input: `{}`,
			expected: AgentPermissions{
				permissions: nil,
			},
			wantErr: false,
		},
		{
			name:  "single permission",
			input: `{"read": "allow"}`,
			expected: AgentPermissions{
				permissions: [][2]string{{"read", "allow"}},
			},
			wantErr: false,
		},
		{
			name:  "multiple permissions - ordered",
			input: `{"read": "allow", "write": "deny", "delete": "deny"}`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"read", "allow"},
					{"write", "deny"},
					{"delete", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name:  "different order",
			input: `{"delete": "deny", "read": "allow", "write": "deny"}`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"delete", "deny"},
					{"read", "allow"},
					{"write", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name:  "different order",
			input: `{"*": "deny", "read": "allow", "write": "deny"}`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"*", "deny"},
					{"read", "allow"},
					{"write", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name:    "invalid json",
			input:   `{"read": "allow"`,
			wantErr: true,
		},
		{
			name:    "non-string value",
			input:   `{"read": 123}`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var ap AgentPermissions
			err := json.Unmarshal([]byte(tt.input), &ap)

			if (err != nil) != tt.wantErr {
				t.Errorf("UnmarshalJSON() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr && !reflect.DeepEqual(ap, tt.expected) {
				t.Errorf("UnmarshalJSON() got = %+v, want %+v", ap, tt.expected)
			}
		})
	}
}

func TestAgentPermissions_MarshalJSON(t *testing.T) {
	tests := []struct {
		name     string
		input    AgentPermissions
		expected string
		wantErr  bool
	}{
		{
			name: "empty permissions",
			input: AgentPermissions{
				permissions: nil,
			},
			expected: `{}`,
		},
		{
			name: "single permission",
			input: AgentPermissions{
				permissions: [][2]string{{"read", "allow"}},
			},
			expected: `{"read":"allow"}`,
		},
		{
			name: "multiple permissions - ordered",
			input: AgentPermissions{
				permissions: [][2]string{
					{"read", "allow"},
					{"write", "deny"},
					{"delete", "deny"},
				},
			},
			expected: `{"read":"allow","write":"deny","delete":"deny"}`,
		},
		{
			name: "permissions with special characters in keys",
			input: AgentPermissions{
				permissions: [][2]string{
					{"key-with-dash", "allow"},
					{"key_with_underscore", "deny"},
				},
			},
			expected: `{"key-with-dash":"allow","key_with_underscore":"deny"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.input)

			if (err != nil) != tt.wantErr {
				t.Errorf("MarshalJSON() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr && string(data) != tt.expected {
				t.Errorf("MarshalJSON() got = %s, want %s", string(data), tt.expected)
			}
		})
	}
}

func TestAgentPermissions_RoundTrip(t *testing.T) {
	tests := []struct {
		name  string
		input string
	}{
		{
			name:  "empty",
			input: `{}`,
		},
		{
			name:  "single permission",
			input: `{"read":"allow"}`,
		},
		{
			name:  "multiple permissions",
			input: `{"read":"allow","write":"deny","delete":"deny","execute":"allow"}`,
		},
		{
			name:  "complex permissions",
			input: `{"resource:read":"allow","resource:write":"deny","resource:delete":"deny","user:create":"allow","user:update":"allow"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Unmarshal
			var ap AgentPermissions
			err := json.Unmarshal([]byte(tt.input), &ap)
			if err != nil {
				t.Fatalf("Unmarshal failed: %v", err)
			}

			// Marshal back
			data, err := json.Marshal(ap)
			if err != nil {
				t.Fatalf("Marshal failed: %v", err)
			}

			// Compare
			if string(data) != tt.input {
				t.Errorf("Round trip failed: got %s, want %s", string(data), tt.input)
			}
		})
	}
}

func TestAgentPermissions_OrderPreservation(t *testing.T) {
	// Test that order is preserved through unmarshal/marshal cycle
	inputs := []string{
		`{"a":"allow","b":"deny","c":"allow","d":"deny"}`,
		`{"z":"deny","y":"allow","x":"deny","w":"allow"}`,
		`{"first":"allow","second":"deny","third":"allow"}`,
	}

	for _, input := range inputs {
		t.Run(input, func(t *testing.T) {
			var ap AgentPermissions
			if err := json.Unmarshal([]byte(input), &ap); err != nil {
				t.Fatalf("Unmarshal failed: %v", err)
			}

			data, err := json.Marshal(ap)
			if err != nil {
				t.Fatalf("Marshal failed: %v", err)
			}

			if string(data) != input {
				t.Errorf("Order not preserved:\n  input: %s\n  output: %s", input, string(data))
			}
		})
	}
}

func TestAgentPermissions_UnmarshalYAML(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected AgentPermissions
		wantErr  bool
	}{
		{
			name:  "empty object",
			input: `{}`,
			expected: AgentPermissions{
				permissions: nil,
			},
			wantErr: false,
		},
		{
			name:  "single permission",
			input: `read: allow`,
			expected: AgentPermissions{
				permissions: [][2]string{{"read", "allow"}},
			},
			wantErr: false,
		},
		{
			name: "multiple permissions - ordered",
			input: `read: allow
write: deny
delete: deny`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"read", "allow"},
					{"write", "deny"},
					{"delete", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name: "different order",
			input: `delete: deny
read: allow
write: deny`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"delete", "deny"},
					{"read", "allow"},
					{"write", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name: "wildcard permission",
			input: `"*": deny
read: allow
write: deny`,
			expected: AgentPermissions{
				permissions: [][2]string{
					{"*", "deny"},
					{"read", "allow"},
					{"write", "deny"},
				},
			},
			wantErr: false,
		},
		{
			name:    "invalid yaml - not a mapping",
			input:   `- read`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var ap AgentPermissions
			err := yaml.Unmarshal([]byte(tt.input), &ap)

			if (err != nil) != tt.wantErr {
				t.Errorf("UnmarshalYAML() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr && !reflect.DeepEqual(ap, tt.expected) {
				t.Errorf("UnmarshalYAML() got = %+v, want %+v", ap, tt.expected)
			}
		})
	}
}

func TestAgentPermissions_MarshalYAML(t *testing.T) {
	tests := []struct {
		name     string
		input    AgentPermissions
		expected string
		wantErr  bool
	}{
		{
			name: "empty permissions",
			input: AgentPermissions{
				permissions: nil,
			},
			expected: "{}\n",
		},
		{
			name: "single permission",
			input: AgentPermissions{
				permissions: [][2]string{{"read", "allow"}},
			},
			expected: "read: allow\n",
		},
		{
			name: "multiple permissions - ordered",
			input: AgentPermissions{
				permissions: [][2]string{
					{"read", "allow"},
					{"write", "deny"},
					{"delete", "deny"},
				},
			},
			expected: `read: allow
write: deny
delete: deny
`,
		},
		{
			name: "permissions with special characters in keys",
			input: AgentPermissions{
				permissions: [][2]string{
					{"key-with-dash", "allow"},
					{"key_with_underscore", "deny"},
				},
			},
			expected: `key-with-dash: allow
key_with_underscore: deny
`,
		},
		{
			name: "wildcard permission",
			input: AgentPermissions{
				permissions: [][2]string{
					{"*", "deny"},
					{"read", "allow"},
				},
			},
			expected: `'*': deny
read: allow
`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := yaml.Marshal(tt.input)

			if (err != nil) != tt.wantErr {
				t.Errorf("MarshalYAML() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr && string(data) != tt.expected {
				t.Errorf("MarshalYAML() got = %q, want %q", string(data), tt.expected)
			}
		})
	}
}

func TestAgentPermissions_RoundTrip_YAML(t *testing.T) {
	tests := []struct {
		name  string
		input string
	}{
		{
			name:  "empty",
			input: "{}\n",
		},
		{
			name:  "single permission",
			input: "read: allow\n",
		},
		{
			name: "multiple permissions",
			input: `read: allow
write: deny
delete: deny
execute: allow
`,
		},
		{
			name: "complex permissions",
			input: `resource:read: allow
resource:write: deny
resource:delete: deny
user:create: allow
user:update: allow
`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Unmarshal
			var ap AgentPermissions
			err := yaml.Unmarshal([]byte(tt.input), &ap)
			if err != nil {
				t.Fatalf("Unmarshal failed: %v", err)
			}

			// Marshal back
			data, err := yaml.Marshal(ap)
			if err != nil {
				t.Fatalf("Marshal failed: %v", err)
			}

			// Compare
			if string(data) != tt.input {
				t.Errorf("Round trip failed: got %q, want %q", string(data), tt.input)
			}
		})
	}
}

func TestAgentPermissions_OrderPreservation_YAML(t *testing.T) {
	// Test that order is preserved through unmarshal/marshal cycle
	inputs := []string{
		`a: allow
b: deny
c: allow
d: deny
`,
		`z: deny
y: allow
x: deny
w: allow
`,
		`first: allow
second: deny
third: allow
`,
	}

	for _, input := range inputs {
		t.Run(input, func(t *testing.T) {
			var ap AgentPermissions
			if err := yaml.Unmarshal([]byte(input), &ap); err != nil {
				t.Fatalf("Unmarshal failed: %v", err)
			}

			data, err := yaml.Marshal(ap)
			if err != nil {
				t.Fatalf("Marshal failed: %v", err)
			}

			if string(data) != input {
				t.Errorf("Order not preserved:\n  input: %q\n  output: %q", input, string(data))
			}
		})
	}
}
