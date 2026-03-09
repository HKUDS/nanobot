package config

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"sigs.k8s.io/yaml"
)

type resource struct {
	resourceType string
	url          string
	parts        []string
	ref          string
	static       *types.Config
}

var (
	NoConfigFoundErr = fmt.Errorf("no configuration found")

	httpCache map[string]struct {
		data []byte
		last time.Time
	}
	httpCacheLock sync.Mutex
	refreshTime   = time.Minute * 15
)

func httpRefresh() {
	for {
		time.Sleep(refreshTime)
		var toRefresh []string

		httpCacheLock.Lock()
		for k, v := range httpCache {
			if time.Since(v.last) > refreshTime {
				toRefresh = append(toRefresh, k)
			}
		}
		httpCacheLock.Unlock()

		for _, k := range toRefresh {
			newData, err := httpGetRaw(context.Background(), k)
			if err != nil {
				continue
			}
			httpCacheLock.Lock()
			httpCache[k] = struct {
				data []byte
				last time.Time
			}{
				data: newData,
			}
			httpCacheLock.Unlock()
		}
	}
}

func httpGet(ctx context.Context, url string) ([]byte, error) {
	httpCacheLock.Lock()
	defer httpCacheLock.Unlock()

	data, ok := httpCache[url]
	if ok {
		return data.data, nil
	}

	httpCacheLock.Unlock()
	newContent, err := httpGetRaw(ctx, url)
	httpCacheLock.Lock()

	if err != nil {
		return nil, err
	}

	if httpCache == nil {
		httpCache = map[string]struct {
			data []byte
			last time.Time
		}{}
		go httpRefresh()
	}

	httpCache[url] = struct {
		data []byte
		last time.Time
	}{
		data: newContent,
		last: time.Now(),
	}

	return newContent, nil
}

func httpGetRaw(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("error creating request for %s: %w", url, err)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("error fetching %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("error fetching %s: status code %d", url, resp.StatusCode)
	}

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("error reading response from %s: %w", url, err)
	}

	return data, nil
}

func (r *resource) Load(ctx context.Context) (result types.Config, _ error) {
	if r.static != nil {
		return *r.static, nil
	}

	data, err := r.read(ctx)
	if err != nil {
		return result, fmt.Errorf("error reading resource %s: %w", r.url, err)
	}

	obj := map[string]any{}
	if err := yaml.Unmarshal(data, &obj); err != nil {
		return result, fmt.Errorf("error unmarshalling resource %s: %w", r.url, err)
	}

	if err := getSchema().Validate(obj); err != nil {
		return result, fmt.Errorf("error validating resource %s: %w", r.url, err)
	}

	if err := mcp.JSONCoerce(obj, &result); err != nil {
		return result, fmt.Errorf("error marshalling resource %s: %w", r.url, err)
	}

	return
}

func (r *resource) SourceRel(source mcp.ServerSource) (mcp.ServerSource, error) {
	if source.Repo != "" || source.SubPath == "" {
		return source, nil
	}

	switch r.resourceType {
	case "http":
		return mcp.ServerSource{}, fmt.Errorf("cannot resolve relative source for config loaded from HTTP: %s", r.url)
	case "path":
		cwd, err := r.Cwd()
		if err != nil {
			return mcp.ServerSource{}, fmt.Errorf("error getting current working directory for %s: %w", r, err)
		}
		cwd, err = filepath.Abs(cwd)
		if err != nil {
			return mcp.ServerSource{}, fmt.Errorf("error getting absolute path for %s: %w", cwd, err)
		}
		subPath := source.SubPath
		for strings.HasPrefix(subPath, "../") {
			subPath = strings.TrimPrefix(subPath, "../")
			cwd = filepath.Dir(cwd)
		}

		source.SubPath = subPath
		source.Repo = cwd
		return source, nil
	case "git":
		source.Repo = fmt.Sprintf("https://%s/%s/%s.git", r.parts[0], r.parts[1], r.parts[2])
		if source.Reference == "" && source.Tag == "" && source.Branch == "" && source.Commit == "" {
			source.Reference = r.ref
		}
		source.SubPath = strings.Join(append(r.parts[3:], source.SubPath), "/")
		return source, nil
	}

	return mcp.ServerSource{}, fmt.Errorf("unknown resource type: %s", r.resourceType)
}

func (r *resource) String() string {
	if len(r.parts) > 0 {
		return strings.Join(r.parts, "/")
	}
	return r.url
}

func (r *resource) read(ctx context.Context) ([]byte, error) {
	if r.resourceType == "http" {
		return httpGet(ctx, r.url)
	}

	if r.resourceType == "path" {
		f, err := r.fileToRead()
		if err != nil {
			return nil, err
		}
		if data, err := os.ReadFile(f); err == nil {
			return data, nil
		} else if !os.IsNotExist(err) {
			return nil, fmt.Errorf("error reading file %s: %w", f, err)
		}

		hasMd, err := hasMarkdownFiles(r.url)
		if err != nil {
			return nil, fmt.Errorf("error checking for markdown files in %s: %w", r.url, err)
		}

		if hasMd {
			// Only markdown files - use directory loader
			return loadFromDirectory(r.url)
		}

		return nil, fmt.Errorf("%w at %s", NoConfigFoundErr, r.url)
	}

	if r.resourceType == "git" {
		return gitRead(ctx, r.parts, r.ref)
	}

	return nil, fmt.Errorf("unknown resource type: %s", r.resourceType)
}

func joinPath(url, path string) string {
	parts := strings.Split(url, "/")
	if len(parts) == 1 {
	}

	dir, file := parts[:len(parts)-1], parts[len(parts)-1]
	if strings.Contains(file, ".") {
		url = strings.Join(dir, "/")
	}

	if !strings.HasSuffix(url, "/") {
		url += "/"
	}

	return url + strings.TrimPrefix(path, "./")
}

func (r *resource) Cwd() (string, error) {
	if r.resourceType != "path" {
		return ".", nil
	}

	file, err := r.fileToRead()
	if err != nil {
		return "", fmt.Errorf("error getting file to read for %s: %w", r.url, err)
	}

	return filepath.Dir(file), nil
}

func (r *resource) fileToRead() (string, error) {
	path := r.url

	s, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("error looking up %s: %w", path, err)
	}

	if s.IsDir() {
		path = filepath.Join(path, "nanobot.yaml")
	}

	return path, nil
}

func (r *resource) Rel(path string) (*resource, error) {
	if staticCfg := statics(path); staticCfg != nil {
		return staticCfg, nil
	}

	switch r.resourceType {
	case "http":
		return &resource{
			resourceType: "http",
			url:          joinPath(r.url, path),
		}, nil
	case "path":
		return &resource{
			resourceType: "path",
			url:          joinPath(r.url, path),
		}, nil
	case "git":
		return &resource{
			resourceType: "git",
			parts:        append(r.parts, path),
			ref:          r.ref,
		}, nil
	}
	return nil, fmt.Errorf("unknown resource type: %s", r.resourceType)
}

func gitRead(ctx context.Context, parts []string, ref string) ([]byte, error) {
	if parts[0] != "github.com" {
		// Handle other git providers or formats
		return nil, fmt.Errorf("git read not implemented for %s", strings.Join(parts, "/"))
	}

	owner, repo := parts[1], parts[2]
	path := strings.Join(parts[3:], "/")
	if path == "" {
		path = "nanobot.yaml"
	}

	if ref == "" {
		ref = "HEAD"
	}

	url := fmt.Sprintf("https://raw.githubusercontent.com/%s/%s/%s/%s", owner, repo, ref, path)
	return httpGet(ctx, url)
}

func statics(name string) *resource {
	switch name {
	case "nanobot.ui":
		return &resource{
			resourceType: "static",
			static:       &UI,
		}
	}
	return nil
}
func resolve(name string) (*resource, error) {
	if staticCfg := statics(name); staticCfg != nil {
		return staticCfg, nil
	}

	if strings.HasPrefix(name, "http://") || strings.HasPrefix(name, "https://") {
		// Handle HTTP resources
		return &resource{
			resourceType: "http",
			url:          name,
		}, nil
	}

	if strings.HasPrefix(name, "/") || strings.HasPrefix(name, ".") {
		// Handle local file paths
		return &resource{
			resourceType: "path",
			url:          name,
		}, nil
	}

	location, ref, _ := strings.Cut(name, "@")
	parts := strings.Split(location, "/")

	if !strings.Contains(parts[0], ".") {
		parts = append([]string{"github.com"}, parts...)
	}

	if len(parts) < 3 {
		return nil, fmt.Errorf("invalid git resource format, must be {owner}/{repo} format: %s", name)
	}

	return &resource{
		resourceType: "git",
		parts:        parts,
		ref:          ref,
	}, nil
}
