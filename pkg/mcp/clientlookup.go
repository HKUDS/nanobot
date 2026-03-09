package mcp

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"
)

type ClientCredLookup interface {
	Lookup(context.Context, string) (string, string, error)
}

func NewClientLookupFromEnv() ClientCredLookup {
	return &envClientCredLookup{}
}

type envClientCredLookup struct{}

func (l *envClientCredLookup) Lookup(_ context.Context, authURL string) (string, string, error) {
	clientIDEnvVar, clientSecretEnvVar, err := AuthURLToEnvVars(authURL)
	if err != nil {
		return "", "", err
	}

	return os.Getenv(clientIDEnvVar), os.Getenv(clientSecretEnvVar), nil
}

func AuthURLToEnvVars(authURL string) (string, string, error) {
	u, err := url.Parse(authURL)
	if err != nil {
		return "", "", fmt.Errorf("failed to parse url: %w", err)
	}

	envBase := strings.ReplaceAll(strings.ReplaceAll(u.Host, ".", "_"), ":", "_")
	if u.Path != "" && u.Path != "/" {
		envBase += strings.ReplaceAll(strings.TrimSuffix(u.Path, "/"), "/", "_")
	}

	envBase = strings.ToUpper(strings.ReplaceAll(envBase, "-", "_"))
	return envBase + "_CLIENT_ID", envBase + "_CLIENT_SECRET", nil
}
