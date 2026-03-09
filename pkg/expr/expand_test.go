package expr

import (
	"testing"
)

func TestCustomExpand(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		mapping  map[string]string
		expected string
	}{
		{
			name:     "simple variable",
			input:    "Hello, ${name}!",
			mapping:  map[string]string{"name": "World"},
			expected: "Hello, World!",
		},
		{
			name:     "variable with curly braces",
			input:    "Value: ${foo{x}}",
			mapping:  map[string]string{"foo{x}": "bar"},
			expected: "Value: bar",
		},
		{
			name:     "nested variables",
			input:    "Nested: ${outer{${inner}}}",
			mapping:  map[string]string{"inner": "value", "outer{value}": "result"},
			expected: "Nested: result",
		},
		{
			name:     "multiple variables",
			input:    "${a} ${b{c}} ${d}",
			mapping:  map[string]string{"a": "first", "b{c}": "second", "d": "third"},
			expected: "first second third",
		},
		{
			name:     "no variables",
			input:    "Plain text",
			mapping:  map[string]string{},
			expected: "Plain text",
		},
		{
			name:     "unclosed variable",
			input:    "Unclosed ${variable",
			mapping:  map[string]string{"variable": "value"},
			expected: "Unclosed ${variable",
		},
		{
			name:     "escaped dollar",
			input:    "Cost: $5.00",
			mapping:  map[string]string{},
			expected: "Cost: $5.00",
		},
		{
			name:     "recursive variable expansion",
			input:    "${foo${bar}}",
			mapping:  map[string]string{"foobaz": "correct", "bar": "baz"},
			expected: "correct",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mapping := func(key string) string {
				return tt.mapping[key]
			}
			result := Expand(tt.input, mapping)
			if result != tt.expected {
				t.Errorf("Expand(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

// TestCustomExpandVsOsExpand tests that Expand handles nested braces correctly
// while os.Expand would not.
func TestCustomExpandNestedBraces(t *testing.T) {
	input := "Value: ${foo{x}}"
	mapping := map[string]string{"foo{x}": "correct", "x": "wrong"}

	mapFunc := func(key string) string {
		return mapping[key]
	}

	result := Expand(input, mapFunc)
	expected := "Value: correct"

	if result != expected {
		t.Errorf("Expand(%q) = %q, want %q", input, result, expected)
	}
}
