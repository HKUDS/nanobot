package expr

import (
	"strings"
)

// Expand is similar to os.Expand but handles nested curly braces correctly.
// It replaces ${var} in the input string with the value returned by the mapping function.
// If var contains curly braces, the entire var name is passed to the mapping function.
func Expand(s string, mapping func(string) string) string {
	// First, check if the string has any unclosed variables
	return expandString(s, mapping, 0)
}

// expandString is a helper function that handles the actual expansion.
// The depth parameter is used to prevent infinite recursion.
func expandString(s string, mapping func(string) string, depth int) string {
	// Prevent infinite recursion
	if depth > 100 {
		return s
	}

	var buf strings.Builder
	// i is the index in s of the next character to be processed
	i := 0
	for j := 0; j < len(s); j++ {
		if s[j] == '$' && j+1 < len(s) {
			if s[j+1] == '{' {
				buf.WriteString(s[i:j])
				// Find the matching closing brace, accounting for nested braces
				start := j + 2 // Skip the "${" prefix
				braceCount := 1
				end := start
				for end < len(s) && braceCount > 0 {
					if s[end] == '{' {
						braceCount++
					} else if s[end] == '}' {
						braceCount--
					}
					end++
				}

				if braceCount == 0 {
					// We found the matching closing brace
					name := s[start : end-1]
					// First, recursively expand any variables in the name
					expandedName := expandString(name, mapping, depth+1)
					buf.WriteString(mapping(expandedName))
					j = end - 1 // -1 because the loop will increment j
					i = end
				} else {
					// This should never happen since we check for unclosed variables first
					return s
				}
			} else {
				// Not a variable reference, just a literal '$'
				buf.WriteString(s[i : j+1])
				i = j + 1
			}
		}
	}

	// Append any remaining characters
	if i < len(s) {
		buf.WriteString(s[i:])
	}

	return buf.String()
}
