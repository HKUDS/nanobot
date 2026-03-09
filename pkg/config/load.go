package config

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/nanobot-ai/nanobot/pkg/config/agents"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func Load(ctx context.Context, path string, includeDefaultAgents bool, profiles ...string) (cfg *types.Config, cwd string, err error) {
	defer func() {
		if err != nil {
			if _, fErr := os.Stat(path); fErr == nil && !strings.HasPrefix(path, "/") && !strings.HasPrefix(path, ".") {
				err = fmt.Errorf("failed to load %q, did you mean ./%s? local files must start with . or /: %w", path, path, err)
			}
		}
	}()
	configResource, err := resolve(path)
	if err != nil {
		return nil, "", fmt.Errorf("error resolving config path %s: %w", path, err)
	}

	cfg, cwd, err = loadResource(ctx, configResource, profiles...)
	if err != nil {
		if !includeDefaultAgents || !errors.Is(err, NoConfigFoundErr) && !errors.Is(err, fs.ErrNotExist) || path != ".nanobot/" {
			return cfg, cwd, err
		}
	} else if !includeDefaultAgents {
		return cfg, cwd, nil
	}

	if cfg == nil {
		cfg = new(types.Config)
	}
	if err := loadBuiltinAgents(cfg); err != nil {
		return nil, "", err
	}

	return cfg, cwd, nil
}

func loadResource(ctx context.Context, configResource *resource, profiles ...string) (*types.Config, string, error) {
	targetCwd, err := configResource.Cwd()
	if err != nil {
		return nil, "", fmt.Errorf("error determining working directory: %w", err)
	}

	last, err := configResource.Load(ctx)
	if err != nil {
		return nil, "", err
	}

	var lastParent *types.Config
	for _, parentRef := range last.Extends {
		parentResource, err := configResource.Rel(parentRef)
		if err != nil {
			return nil, "", fmt.Errorf("error resolving extends %s: %w", last.Extends, err)
		}

		parent, err := parentResource.Load(ctx)
		if err != nil {
			return nil, "", fmt.Errorf("error loading parent config %s: %w", parentResource.url, err)
		}

		if lastParent == nil {
			lastParent = &parent
		} else {
			merged, err := Merge(*lastParent, parent)
			if err != nil {
				return nil, "", fmt.Errorf("error merging parent config %s: %w", parentResource.url, err)
			}
			lastParent = &merged
		}
	}

	if lastParent != nil {
		last, err = Merge(*lastParent, last)
		if err != nil {
			return nil, "", fmt.Errorf("error merging %s: %w", last.Extends, err)
		}
	}

	for _, profile := range profiles {
		profileName, _, optional := strings.Cut(profile, "?")
		profileConfig, found := last.Profiles[profileName]
		if !found && !optional {
			return nil, "", fmt.Errorf("profile %s not found", profileName)
		} else if !found {
			continue
		}
		var err error
		last, err = Merge(last, profileConfig)
		if err != nil {
			return nil, "", fmt.Errorf("error merging profile %s: %w", profileName, err)
		}
	}

	last = rewriteCwd(last, targetCwd)

	last, err = rewriteSourceReferences(last, configResource)
	if err != nil {
		return nil, "", fmt.Errorf("error rewriting source references: %w", err)
	}

	if len(last.Agents) == 1 && len(last.Publish.Entrypoint) == 0 {
		for agentName := range last.Agents {
			last.Publish.Entrypoint = append(last.Publish.Entrypoint, agentName)
		}
	}

	return &last, targetCwd, last.Validate(configResource.resourceType == "path")
}

func rewriteCwd(cfg types.Config, cwd string) types.Config {
	newMCPServers := map[string]mcp.Server{}
	for name, mcpServer := range cfg.MCPServers {
		mcpServer.Cwd = filepath.Join(cwd, mcpServer.Cwd)
		newMCPServers[name] = mcpServer
	}
	cfg.MCPServers = newMCPServers
	return cfg
}

func rewriteSourceReferences(cfg types.Config, resource *resource) (types.Config, error) {
	for name, mcpServer := range cfg.MCPServers {
		var err error
		mcpServer.Source, err = resource.SourceRel(mcpServer.Source)
		if err != nil {
			return types.Config{}, fmt.Errorf("error resolving source for MCP server %s: %w", name, err)
		}
		cfg.MCPServers[name] = mcpServer
	}
	return cfg, nil
}

func toMap(cfg types.Config) (map[string]any, error) {
	result := map[string]any{}
	data, err := json.Marshal(cfg)
	if err != nil {
		return nil, err
	}
	return result, json.Unmarshal(data, &result)
}

func mergeObject(base, overlay any) any {
	if baseMap, ok := base.(map[string]any); ok {
		if overlayMap, ok := overlay.(map[string]any); ok {
			newMap := maps.Clone(baseMap)
			for k, v := range overlayMap {
				newMap[k] = mergeObject(baseMap[k], v)
			}
			return newMap
		}
	}
	if baseArray, ok := base.([]any); ok {
		if overlayArray, ok := overlay.([]any); ok {
			return slices.Concat(baseArray, overlayArray)
		}
	}
	return overlay
}

func Merge(base, overlay types.Config) (types.Config, error) {
	baseMap, err := toMap(base)
	if err != nil {
		return types.Config{}, err
	}
	overlayMap, err := toMap(overlay)
	if err != nil {
		return types.Config{}, err
	}

	merged := mergeObject(baseMap, overlayMap)
	mergedData, err := json.Marshal(merged)
	if err != nil {
		return types.Config{}, err
	}

	var result types.Config
	return result, json.Unmarshal(mergedData, &result)
}

// loadBuiltinAgents reads built-in agent definitions from the embedded filesystem
// and adds them to the config.
func loadBuiltinAgents(cfg *types.Config) error {
	// Initialize agents map if nil
	if cfg.Agents == nil {
		cfg.Agents = make(map[string]types.Agent)
	}

	// Read all entries from the embedded filesystem
	entries, err := fs.ReadDir(agents.Builtin, ".")
	if err != nil {
		return fmt.Errorf("failed to read builtin agents directory: %w", err)
	}

	// Process each .md file
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".md") {
			continue
		}

		// Extract agent name from filename (remove .md extension)
		agentName := strings.TrimSuffix(entry.Name(), ".md")

		// Check if agent already exists in config (built-in agents are always present)
		if _, exists := cfg.Agents[agentName]; exists {
			return fmt.Errorf("cannot override built-in agent %q: agent name is reserved", agentName)
		}

		// Read the markdown file
		content, err := fs.ReadFile(agents.Builtin, entry.Name())
		if err != nil {
			return fmt.Errorf("failed to read builtin agent %q: %w", entry.Name(), err)
		}

		// Parse frontmatter and body
		frontmatterYAML, body, err := parseFrontMatter(content)
		if err != nil {
			return fmt.Errorf("failed to parse frontmatter for builtin agent %q: %w", entry.Name(), err)
		}

		// If no frontmatter, treat entire content as instructions
		var agentFromYAML frontMatterAgent
		if frontmatterYAML != nil {
			if err := yaml.Unmarshal(frontmatterYAML, &agentFromYAML); err != nil {
				return fmt.Errorf("failed to unmarshal frontmatter for builtin agent %q: %w", entry.Name(), err)
			}
		}

		// Use the body as instructions without any prefix
		agentFromYAML.Instructions = types.DynamicInstructions{
			Instructions: body,
		}

		// Create the agent
		agent := types.Agent{
			HookAgent: agentFromYAML.HookAgent,
		}

		// Add to config
		cfg.Agents[agentName] = agent

		// If the agent is not marked as a subagent, then add it to the entrypoint list
		if agentFromYAML.Mode != "subagent" {
			cfg.Publish.Entrypoint = append(cfg.Publish.Entrypoint, agentName)
		}
	}

	return nil
}
