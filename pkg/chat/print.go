package chat

import (
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
)

func writeData(output io.Writer, result mcp.Content) error {
	data, err := base64.StdEncoding.DecodeString(result.Data)
	if err != nil {
		return err
	}
	i := 1
	for {
		filename := fmt.Sprintf("output%d.data", i)
		_, err := os.Stat(filename)
		if !errors.Is(err, fs.ErrNotExist) {
			i++
			continue
		}

		if err := os.WriteFile(filename, data, 0644); err != nil {
			return err
		}
		name := result.Type
		if result.MIMEType != "" {
			name += "(" + result.MIMEType + ")"
		}
		_, _ = fmt.Fprintf(output, "%s written to %s\n", name, filename)
		return nil
	}
}

func PrintResult(output io.Writer, result *mcp.CallToolResult) error {
	for _, out := range result.Content {
		if out.Text != "" {
			_, _ = fmt.Fprintln(output, out.Text)
		} else if out.Data != "" {
			if err := writeData(output, out); err != nil {
				return err
			}
		}
	}

	return nil
}
