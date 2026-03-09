package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/adrg/xdg"
	"golang.org/x/oauth2"
)

const localTokenFileName = "tokens.json"

type TokenStorage interface {
	GetTokenConfig(context.Context, string) (*oauth2.Config, *oauth2.Token, error)
	SetTokenConfig(context.Context, string, *oauth2.Config, *oauth2.Token) error
	DeleteTokenConfig(context.Context, string) error
}

func NewDefaultLocalStorage() TokenStorage {
	return NewLocalTokenStorage(xdg.DataHome + "/nanobot")
}

func NewLocalTokenStorage(dir string) TokenStorage {
	return &localTokenStorage{
		dir: dir,
	}
}

type localTokenStorage struct {
	dir string
}

type localData struct {
	Config *oauth2.Config `json:"config,omitempty"`
	Token  *oauth2.Token  `json:"token,omitempty"`
}

func (l *localTokenStorage) GetTokenConfig(_ context.Context, url string) (*oauth2.Config, *oauth2.Token, error) {
	m, err := l.readFile()
	if err != nil {
		return nil, nil, err
	}

	d := m[url]
	return d.Config, d.Token, nil
}

func (l *localTokenStorage) SetTokenConfig(_ context.Context, url string, config *oauth2.Config, token *oauth2.Token) error {
	m, err := l.readFile()
	if err != nil {
		return err
	}

	m[url] = localData{
		Config: config,
		Token:  token,
	}

	return l.writeFile(m)
}

func (l *localTokenStorage) readFile() (map[string]localData, error) {
	data, err := os.ReadFile(filepath.Join(l.dir, localTokenFileName))
	if errors.Is(err, os.ErrNotExist) {
		return make(map[string]localData), nil
	} else if err != nil {
		return nil, fmt.Errorf("failed to read token file: %w", err)
	}

	var m map[string]localData
	return m, json.Unmarshal(data, &m)
}

func (l *localTokenStorage) writeFile(m map[string]localData) error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal token data: %w", err)
	}

	if err = os.MkdirAll(l.dir, 0700); err != nil {
		return fmt.Errorf("failed to create token directory: %w", err)
	}

	if err = os.WriteFile(filepath.Join(l.dir, localTokenFileName), data, 0600); err != nil {
		return fmt.Errorf("failed to write token file: %w", err)
	}

	return nil
}

func (l *localTokenStorage) DeleteTokenConfig(_ context.Context, url string) error {
	m, err := l.readFile()
	if err != nil {
		return err
	}

	delete(m, url)
	return l.writeFile(m)
}
