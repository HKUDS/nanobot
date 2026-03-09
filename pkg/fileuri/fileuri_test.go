package fileuri

import (
	"testing"
)

func TestEncode(t *testing.T) {
	tests := []struct {
		name    string
		relPath string
		want    string
	}{
		{"simple", "test.txt", "file:///test.txt"},
		{"subdirectory", "subdir/file.txt", "file:///subdir/file.txt"},
		{"space in name", "Screenshot 2024.png", "file:///Screenshot%202024.png"},
		{"multiple segments with spaces", "my dir/my file.txt", "file:///my%20dir/my%20file.txt"},
		{"hash in name", "notes#1.txt", "file:///notes%231.txt"},
		{"percent in name", "100%.txt", "file:///100%25.txt"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Encode(tt.relPath)
			if got != tt.want {
				t.Errorf("Encode(%q) = %q, want %q", tt.relPath, got, tt.want)
			}
		})
	}
}

func TestDecode(t *testing.T) {
	tests := []struct {
		name    string
		uri     string
		want    string
		wantErr bool
	}{
		{"simple", "file:///test.txt", "test.txt", false},
		{"encoded space", "file:///Screenshot%202024.png", "Screenshot 2024.png", false},
		{"unencoded space (legacy)", "file:///Screenshot 2024.png", "Screenshot 2024.png", false},
		{"subdirectory encoded", "file:///my%20dir/my%20file.txt", "my dir/my file.txt", false},
		{"hash encoded", "file:///notes%231.txt", "notes#1.txt", false},
		{"missing prefix", "https:///test.txt", "", true},
		{"empty path", "file:///", "", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := Decode(tt.uri)
			if (err != nil) != tt.wantErr {
				t.Errorf("Decode(%q) error = %v, wantErr %v", tt.uri, err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("Decode(%q) = %q, want %q", tt.uri, got, tt.want)
			}
		})
	}
}

func TestRoundTrip(t *testing.T) {
	paths := []string{
		"test.txt",
		"subdir/file.txt",
		"Screenshot 2024-07-03 at 11.24.24 AM.png",
		"my dir/my file.txt",
		"notes#1.txt",
		"100%.txt",
	}
	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			uri := Encode(path)
			decoded, err := Decode(uri)
			if err != nil {
				t.Fatalf("Decode(Encode(%q)) error: %v", path, err)
			}
			if decoded != path {
				t.Errorf("round-trip failed: Encode(%q) = %q, Decode = %q", path, uri, decoded)
			}
		})
	}
}

func TestSafeFilename(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{"no change", "normal file.txt", "normal file.txt"},
		{"narrow no-break space", "Screenshot\u202fAM.png", "Screenshot AM.png"},
		{"no-break space", "no\u00a0break.txt", "no break.txt"},
		{"multiple unicode spaces", "a\u202fb\u00a0c.txt", "a b c.txt"},
		{"tabs preserved as space", "a\tb.txt", "a b.txt"},
		{"newline to space", "a\nb.txt", "a b.txt"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := SafeFilename(tt.input)
			if got != tt.want {
				t.Errorf("SafeFilename(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}
