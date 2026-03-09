package fileuri

import (
	"fmt"
	"net/url"
	"path/filepath"
	"strings"
	"unicode"
)

const scheme = "file:///"

// Encode converts a relative file path to a properly percent-encoded file:/// URI.
// Each path segment is individually encoded to preserve "/" separators.
func Encode(relPath string) string {
	segments := strings.Split(filepath.ToSlash(relPath), "/")
	for i, seg := range segments {
		segments[i] = url.PathEscape(seg)
	}
	return scheme + strings.Join(segments, "/")
}

// Decode extracts and percent-decodes the relative path from a file:/// URI.
// Returns an error if the URI doesn't have the file:/// prefix or decoding fails.
func Decode(uri string) (string, error) {
	raw, ok := strings.CutPrefix(uri, scheme)
	if !ok {
		return "", fmt.Errorf("invalid file URI, expected file:///path: %s", uri)
	}
	if raw == "" {
		return "", fmt.Errorf("file path is required in URI: %s", uri)
	}
	decoded, err := url.PathUnescape(raw)
	if err != nil {
		return "", fmt.Errorf("failed to decode file URI %s: %w", uri, err)
	}
	return decoded, nil
}

// SafeFilename replaces Unicode space characters (e.g. U+202F NARROW NO-BREAK SPACE
// commonly found in macOS screenshot filenames) with regular ASCII space.
func SafeFilename(s string) string {
	var (
		b       strings.Builder
		changed bool
	)
	for _, r := range s {
		if r != ' ' && unicode.IsSpace(r) {
			b.WriteRune(' ')
			changed = true
			continue
		}
		b.WriteRune(r)
	}
	if !changed {
		return s
	}
	return b.String()
}
