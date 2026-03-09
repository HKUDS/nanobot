package config

import (
	"bytes"
	"fmt"
	"strings"
)

const frontMatterDelimiter = "---"

// parseFrontMatter extracts YAML front-matter and body from markdown content.
// Front-matter must be delimited by --- at the start and end.
// Returns: (frontMatterYAML []byte, body string, error)
//
// Examples:
//
//	---
//	title: My Document
//	---
//	Content here
//
// Returns: ([]byte("title: My Document\n"), "Content here", nil)
func parseFrontMatter(content []byte) ([]byte, string, error) {
	// Normalize line endings to \n
	normalized := bytes.ReplaceAll(content, []byte("\r\n"), []byte("\n"))
	text := string(normalized)

	// Check if content starts with front-matter delimiter
	if !strings.HasPrefix(text, frontMatterDelimiter+"\n") && !strings.HasPrefix(text, frontMatterDelimiter+"\r") {
		// No front-matter, return entire content as body
		return nil, strings.TrimSpace(text), nil
	}

	// Find the closing delimiter
	// Start searching after the opening "---\n"
	lines := strings.Split(text, "\n")

	closingIndex := -1
	for i := 1; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == frontMatterDelimiter {
			closingIndex = i
			break
		}
	}

	if closingIndex == -1 {
		return nil, "", fmt.Errorf("front-matter missing closing delimiter (---)")
	}

	// Extract front-matter (between the two --- delimiters)
	yamlLines := lines[1:closingIndex]
	yamlContent := []byte(strings.Join(yamlLines, "\n"))

	// Extract body (everything after closing delimiter)
	var bodyLines []string
	if closingIndex+1 < len(lines) {
		bodyLines = lines[closingIndex+1:]
	}
	body := strings.TrimSpace(strings.Join(bodyLines, "\n"))

	return yamlContent, body, nil
}
