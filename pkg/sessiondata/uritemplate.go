package sessiondata

import (
	"fmt"
	"regexp"
	"strings"
)

func uriToRegexp(template string) (*regexp.Regexp, error) {
	// Build regex by processing the template character by character
	var result strings.Builder
	result.WriteByte('^')

	var i int
	for i < len(template) {
		if template[i] == '{' {
			// Find the end of the template variable
			end := strings.Index(template[i:], "}")
			if end == -1 {
				return nil, fmt.Errorf("unclosed template variable in %q", template)
			}
			end += i

			// Extract parameter name
			param := template[i+1 : end]

			// Convert parameter to regex pattern
			if strings.HasPrefix(param, "/") && strings.HasSuffix(param, "*") {
				// {/path*} - optional path segment that can contain slashes
				result.WriteString("(/.*?)?")
			} else if strings.HasSuffix(param, "*") {
				// {param*} - parameter that can contain slashes
				result.WriteString("(.*?)")
			} else {
				// {param} - regular parameter that cannot contain slashes
				result.WriteString("([^/]+?)")
			}

			i = end + 1
		} else {
			// Escape literal character for regex
			result.WriteString(regexp.QuoteMeta(string(template[i])))
			i++
		}
	}

	result.WriteByte('$')
	return regexp.Compile(result.String())
}
