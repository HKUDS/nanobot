package system

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/nanobot-ai/nanobot/pkg/types"
)

func TestRead(t *testing.T) {
	tmp := t.TempDir()
	write := func(name, content string) string {
		p := filepath.Join(tmp, name)
		os.WriteFile(p, []byte(content), 0644)
		return p
	}

	s := &Server{}

	t.Run("empty file_path", func(t *testing.T) {
		_, err := s.read(t.Context(), ReadParams{})
		if err == nil || !strings.Contains(err.Error(), "file_path is required") {
			t.Errorf("expected file_path required error, got %v", err)
		}
	})

	t.Run("text defaults", func(t *testing.T) {
		path := write("test.txt", "line one\nline two\nline three\n")
		result, err := s.read(t.Context(), ReadParams{FilePath: path})
		if err != nil {
			t.Fatal(err)
		}
		text := result.Content[0].Text
		if !strings.Contains(text, "line one") || !strings.Contains(text, "line three") {
			t.Errorf("expected all lines, got %q", text)
		}
	})

	t.Run("text offset and limit", func(t *testing.T) {
		path := write("five.txt", "a\nb\nc\nd\ne\n")
		offset, limit := 2, 2
		result, err := s.read(t.Context(), ReadParams{FilePath: path, Offset: &offset, Limit: &limit})
		if err != nil {
			t.Fatal(err)
		}
		text := result.Content[0].Text
		if !strings.Contains(text, "\tc\n") || !strings.Contains(text, "\td\n") {
			t.Errorf("expected lines 3-4, got %q", text)
		}
		if strings.Contains(text, "\ta\n") || strings.Contains(text, "\te\n") {
			t.Errorf("should not contain lines outside range, got %q", text)
		}
	})

	t.Run("text long lines truncated", func(t *testing.T) {
		longLine := strings.Repeat("x", maxLineLength+500)
		path := write("long.txt", longLine+"\n")
		result, err := s.read(t.Context(), ReadParams{FilePath: path})
		if err != nil {
			t.Fatal(err)
		}
		if c := strings.Count(result.Content[0].Text, "x"); c != maxLineLength {
			t.Errorf("expected %d x's, got %d", maxLineLength, c)
		}
	})

	t.Run("text rejects pages", func(t *testing.T) {
		path := write("t.txt", "x\n")
		p := "1-5"
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Pages: &p})
		if err == nil || !strings.Contains(err.Error(), "pages is only supported for PDF") {
			t.Errorf("expected pages rejection, got %v", err)
		}
	})

	t.Run("text negative offset", func(t *testing.T) {
		path := write("t.txt", "x\n")
		offset := -1
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Offset: &offset})
		if err == nil || !strings.Contains(err.Error(), "offset must be >= 0") {
			t.Errorf("expected offset error, got %v", err)
		}
	})

	t.Run("text zero limit", func(t *testing.T) {
		path := write("t.txt", "x\n")
		limit := 0
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Limit: &limit})
		if err == nil || !strings.Contains(err.Error(), "limit must be > 0") {
			t.Errorf("expected limit error, got %v", err)
		}
	})

	t.Run("text nonexistent file", func(t *testing.T) {
		_, err := s.read(t.Context(), ReadParams{FilePath: filepath.Join(tmp, "nope.txt")})
		if err == nil {
			t.Fatal("expected error")
		}
	})

	t.Run("image correct mime", func(t *testing.T) {
		path := write("test.png", "fake png")
		result, err := s.read(t.Context(), ReadParams{FilePath: path})
		if err != nil {
			t.Fatal(err)
		}
		if result.Content[0].MIMEType != "image/png" {
			t.Errorf("expected image/png, got %s", result.Content[0].MIMEType)
		}
		skipMeta, _ := result.Content[0].Meta[types.SkipTruncationMetaKey].(bool)
		if !skipMeta {
			t.Error("expected skip-truncation meta on content")
		}
	})

	t.Run("image rejects offset", func(t *testing.T) {
		path := write("t.png", "fake")
		v := 1
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Offset: &v})
		if err == nil || !strings.Contains(err.Error(), "not supported for image") {
			t.Errorf("expected rejection, got %v", err)
		}
	})

	t.Run("image rejects limit", func(t *testing.T) {
		path := write("t.png", "fake")
		v := 1
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Limit: &v})
		if err == nil || !strings.Contains(err.Error(), "not supported for image") {
			t.Errorf("expected rejection, got %v", err)
		}
	})

	t.Run("image rejects pages", func(t *testing.T) {
		path := write("t.png", "fake")
		p := "1"
		_, err := s.read(t.Context(), ReadParams{FilePath: path, Pages: &p})
		if err == nil || !strings.Contains(err.Error(), "not supported for image") {
			t.Errorf("expected rejection, got %v", err)
		}
	})
}

func TestParsePagesRange(t *testing.T) {
	ptr := func(s string) *string { return &s }

	tests := []struct {
		name        string
		pages       *string
		totalPages  int
		first, last int
		wantErr     string
	}{
		{name: "nil 5 pages", pages: nil, totalPages: 5, first: 1, last: 5},
		{name: "nil 10 pages", pages: nil, totalPages: 10, first: 1, last: 10},
		{name: "nil 11 pages", pages: nil, totalPages: 11, wantErr: "please specify a pages"},
		{name: "single page", pages: ptr("3"), totalPages: 10, first: 3, last: 3},
		{name: "range", pages: ptr("2-5"), totalPages: 10, first: 2, last: 5},
		{name: "range with spaces", pages: ptr(" 2 - 5 "), totalPages: 10, first: 2, last: 5},
		{name: "clamp last", pages: ptr("8-15"), totalPages: 10, first: 8, last: 10},
		{name: "first beyond total", pages: ptr("11"), totalPages: 10, wantErr: "exceeds PDF page count"},
		{name: "reversed range", pages: ptr("5-3"), totalPages: 10, wantErr: "must be >= first"},
		{name: "zero page", pages: ptr("0"), totalPages: 10, wantErr: "must be >= 1"},
		{name: "invalid number", pages: ptr("abc"), totalPages: 10, wantErr: "invalid page number"},
		{name: "invalid last", pages: ptr("1-abc"), totalPages: 10, wantErr: "invalid page number"},
		{name: "exceeds max pages", pages: ptr("1-25"), totalPages: 30, wantErr: "maximum is"},
		{name: "exceeds max after clamp", pages: ptr("1-100"), totalPages: 30, wantErr: "maximum is"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			first, last, err := parsePagesRange(tt.pages, tt.totalPages)
			if tt.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
					t.Errorf("expected error containing %q, got %v", tt.wantErr, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if first != tt.first || last != tt.last {
				t.Errorf("got (%d, %d), want (%d, %d)", first, last, tt.first, tt.last)
			}
		})
	}
}
