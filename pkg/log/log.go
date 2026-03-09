package log

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os"
	"regexp"
	"slices"
	"strings"
)

var (
	debugs            = parseDebugTokens(os.Getenv("NANOBOT_DEBUG"))
	EnableMessages    = hasDebugToken("messages")
	EnableProgress    = hasDebugToken("progress")
	EnableUI          = hasDebugToken("ui")
	Base64Replace     = regexp.MustCompile(`((;base64,|")[a-zA-Z0-9+/=]{60})[a-zA-Z0-9+/=]+"`)
	Base64Replacement = []byte(`$1..."`)
)

func parseDebugTokens(raw string) []string {
	parts := strings.Split(raw, ",")
	tokens := make([]string, 0, len(parts))
	for _, part := range parts {
		token := strings.ToLower(strings.TrimSpace(part))
		if token == "" || slices.Contains(tokens, token) {
			continue
		}
		tokens = append(tokens, token)
	}
	return tokens
}

func hasDebugToken(token string) bool {
	return slices.Contains(debugs, strings.ToLower(strings.TrimSpace(token)))
}

func init() {
	ConfigureSlog(false, false)
}

func ConfigureSlog(debug, trace bool) {
	level := slog.LevelInfo
	if len(debugs) > 0 || debug || trace {
		level = slog.LevelDebug
	}

	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
		Level: level,
	})))
}

func Messages(_ context.Context, server string, out bool, data []byte) {
	if !EnableUI && server == "nanobot.ui" {
		return
	}

	if EnableProgress && bytes.Contains(data, []byte(`"notifications/progress"`)) {
	} else if EnableMessages && !bytes.Contains(data, []byte(`"notifications/progress"`)) {
	} else if hasDebugToken(server) {
	} else {
		return
	}

	prefixFmt := "->(%s)"
	if !out {
		prefixFmt = "<-(%s)"
	}

	data = Base64Replace.ReplaceAll(data, Base64Replacement)
	slog.Debug("mcp message", "prefix", fmt.Sprintf(prefixFmt, server), "payload", strings.ReplaceAll(strings.TrimSpace(string(data)), "\n", " "))
}

func StderrMessages(_ context.Context, server, line string) {
	slog.Info("mcp stderr", "server", server, "stream", "stderr", "line", strings.TrimRight(line, "\n"))
}
