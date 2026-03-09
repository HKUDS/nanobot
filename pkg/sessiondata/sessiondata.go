package sessiondata

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"net/http"
	"slices"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/complete"
	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/schema"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"log/slog"
)

const (
	toolMappingKey                  = "toolMapping"
	promptMappingKey                = "promptMapping"
	resourceMappingKey              = "resourceMapping"
	resourceTemplateMappingKey      = "resourceTemplateMapping"
	resourceTemplateMappingCacheKey = "resourceTemplateMappingCache"
	agentsSessionKey                = "agents"
	currentAgentTargetSessionKey    = "currentAgentTargetMapping"
)

type Data struct {
	runtime RuntimeMeta
}

func NewData(runtime RuntimeMeta) *Data {
	return &Data{
		runtime: runtime,
	}
}

type RuntimeMeta interface {
	BuildToolMappings(ctx context.Context, toolList []string, opts ...types.BuildToolMappingsOptions) (types.ToolMappings, error)
	GetClient(ctx context.Context, name string) (*mcp.Client, error)
	GetAgentAttributes(ctx context.Context, name string) (agentConfigName string, agentAttribute map[string]any, _ error)
}

type GetOption struct {
	AllowMissing bool
	ForceFetch   bool
}

func (g GetOption) Merge(other GetOption) (result GetOption) {
	result.AllowMissing = complete.Last(g.AllowMissing, other.AllowMissing)
	result.ForceFetch = complete.Last(g.ForceFetch, other.ForceFetch)
	return
}

func WithAllowMissing() GetOption {
	return GetOption{
		AllowMissing: true,
	}
}

func (d *Data) getEntrypoints(ctx context.Context) []string {
	c := types.ConfigFromContext(ctx)
	return c.Publish.Entrypoint
}

func (d *Data) SetCurrentAgent(ctx context.Context, newAgent string) error {
	if newAgent == types.CurrentAgent(ctx) {
		return nil
	}

	entrypoints := d.getEntrypoints(ctx)
	session := mcp.SessionFromContext(ctx)
	for session.Parent != nil {
		session = session.Parent
	}

	d.Refresh(ctx, false)
	if newAgent == "" {
		session.Delete(types.CurrentAgentSessionKey)
		return nil
	}

	if !slices.Contains(entrypoints, newAgent) {
		return fmt.Errorf("agent %s not found in entrypoints", newAgent)
	}

	session.Set(types.CurrentAgentSessionKey, mcp.SavedString(newAgent))
	return nil
}

func (d *Data) Agents(ctx context.Context) ([]types.AgentDisplay, error) {
	var (
		session = mcp.SessionFromContext(ctx)
		agents  []types.AgentDisplay
		c       types.Config
	)

	if found := session.Get(agentsSessionKey, &agents); found {
		return agents, nil
	}

	session.Get(types.ConfigSessionKey, &c)
	currentAgent := types.CurrentAgent(ctx)

	for _, key := range d.getEntrypoints(ctx) {
		var (
			agentDisplay types.AgentDisplay
		)

		if agent, ok := c.Agents[key]; ok {
			agentDisplay = agent.ToDisplay(key)
			agentDisplay.Current = key == currentAgent
		} else if mcpServer, ok := c.MCPServers[key]; ok {
			c, err := d.runtime.GetClient(ctx, key)
			if err != nil {
				return agents, err
			}

			name := c.Session.InitializeResult.ServerInfo.Name
			if name == "" {
				name = key
			}

			icon, _ := c.Session.InitializeResult.Capabilities.Experimental["ai.nanobot.meta/icon"].(string)
			iconDark, _ := c.Session.InitializeResult.Capabilities.Experimental["ai.nanobot.meta/icon"].(string)
			starterMessages, _ := c.Session.InitializeResult.Capabilities.Experimental["ai.nanobot.meta/starter-messages"].(string)

			agentDisplay = types.AgentDisplay{
				ID:              key,
				Name:            complete.First(c.Session.InitializeResult.ServerInfo.Name, mcpServer.Name, mcpServer.ShortName, key),
				ShortName:       complete.First(mcpServer.ShortName, c.Session.InitializeResult.ServerInfo.Name, mcpServer.Name, key),
				Description:     strings.TrimSpace(mcpServer.Description),
				Icon:            icon,
				IconDark:        iconDark,
				StarterMessages: strings.Split(starterMessages, ","),
			}
		} else {
			continue
		}

		agents = append(agents, agentDisplay)
	}

	session.Set(agentsSessionKey, &agents)
	return agents, nil
}

func (d *Data) setURL(ctx context.Context) {
	var (
		session = mcp.SessionFromContext(ctx)
	)

	req := mcp.RequestFromContext(ctx)
	if req == nil {
		return
	}

	url := GetHostURL(req)
	session.Set(types.PublicURLSessionKey, mcp.SavedString(url))
}

func GetHostURL(req *http.Request) string {
	scheme := req.Header.Get("X-Forwarded-Proto")
	if scheme == "" {
		if req.TLS != nil {
			scheme = "https"
		} else {
			scheme = "http"
		}
	}

	host := req.Header.Get("X-Forwarded-Host")
	if host == "" {
		host = req.Host
	}

	if originalURL := req.Header.Get("X-Original-URL"); originalURL != "" {
		if strings.HasPrefix(originalURL, "http://") || strings.HasPrefix(originalURL, "https://") {
			return originalURL
		}
		return fmt.Sprintf("%s://%s%s", scheme, host, originalURL)
	}

	q := ""
	if req.URL.RawQuery != "" || req.URL.Fragment != "" {
		_, p, _ := strings.Cut(req.URL.String(), "?")
		q = "?" + p
	}

	return fmt.Sprintf("%s://%s%s%s", scheme, host, req.URL.Path, q)
}

func (d *Data) getAndSetConfig(ctx context.Context, defaultConfig types.ConfigFactory) (types.Config, error) {
	var (
		c        types.Config
		nctx     = types.NanobotContext(ctx)
		session  = mcp.SessionFromContext(ctx)
		profiles string
		err      error
	)

	if len(nctx.Profile) > 0 {
		profiles = strings.Join(nctx.Profile, ",")
	} else if req := mcp.RequestFromContext(ctx); req != nil && strings.Contains(req.URL.Path, "/profile/") {
		_, v, ok := strings.Cut(req.URL.Path, "/profile/")
		if ok {
			profiles = strings.TrimSpace(v)
		}
	}

	if nctx.Config != nil {
		c, err = nctx.Config(ctx, profiles)
		if err != nil {
			return c, fmt.Errorf("failed to load config: %w", err)
		}
	} else {
		c, err = defaultConfig(ctx, profiles)
		if err != nil {
			return c, fmt.Errorf("failed to load default config: %w", err)
		}
	}

	session.Set(types.ConfigSessionKey, &c)
	return c, nil
}

func initSubscriptions(session *mcp.Session) {
	var set bool
	if session.Get("_subscriptions_initialized", &set) {
		return
	}

	session.AddFilter(func(ctx context.Context, msg *mcp.Message) (*mcp.Message, error) {
		if msg.Method != "notifications/resources/updated" {
			return msg, nil
		}

		var uri string
		err := json.Unmarshal(msg.Params, &struct {
			URI *string `json:"uri"`
		}{
			URI: &uri,
		})
		if err != nil {
			return msg, nil
		}

		subs := resourceSubscriptions{}
		if session.Get(types.ResourceSubscriptionsSessionKey, &subs) {
			_, ok := subs[uri]
			if ok {
				return msg, nil
			}
		}

		return nil, nil
	})

	session.Set("_subscriptions_initialized", true)
}

type resourceSubscriptions map[string]struct{}

func (r resourceSubscriptions) Deserialize(v any) (any, error) {
	r = resourceSubscriptions{}
	return r, mcp.JSONCoerce(v, &r)
}

func (r resourceSubscriptions) Serialize() (any, error) {
	return (map[string]struct{})(r), nil
}

func (d *Data) UnsubscribeFromResources(ctx context.Context, uris ...string) error {
	var (
		session = mcp.SessionFromContext(ctx)
		subs    resourceSubscriptions
	)
	session.Get(types.ResourceSubscriptionsSessionKey, &subs)
	for _, uri := range uris {
		if _, ok := subs[uri]; ok {
			target, resourceName, err := d.MatchPublishedResource(ctx, uri)
			if err != nil {
				return fmt.Errorf("failed to read resource %s: %v", uri, err)
			}

			c, err := d.runtime.GetClient(ctx, target)
			if err != nil {
				return fmt.Errorf("failed to get client for server %s: %w", target, err)
			}

			if _, err = c.UnsubscribeResource(ctx, resourceName); err != nil {
				return fmt.Errorf("failed to subscribe to resource %s on server %s: %w", resourceName, target, err)
			}

			delete(subs, uri)
		}
	}

	session.Set(types.ResourceSubscriptionsSessionKey, subs)
	return nil
}

func (d *Data) SubscribeToResources(ctx context.Context, uris ...string) error {
	var (
		session = mcp.SessionFromContext(ctx)
		subs    resourceSubscriptions
	)
	session.Get(types.ResourceSubscriptionsSessionKey, &subs)
	if subs == nil {
		subs = resourceSubscriptions{}
	}

	for _, uri := range uris {
		if _, ok := subs[uri]; !ok {
			target, resourceName, err := d.MatchPublishedResource(ctx, uri)
			if err != nil {
				return fmt.Errorf("failed to read resource %s: %v", uri, err)
			}

			c, err := d.runtime.GetClient(ctx, target)
			if err != nil {
				return fmt.Errorf("failed to get client for server %s: %w", target, err)
			}

			if _, err = c.SubscribeResource(ctx, resourceName); err != nil {
				return fmt.Errorf("failed to subscribe to resource %s on server %s: %w", resourceName, target, err)
			}

			subs[uri] = struct{}{}
		}
	}

	session.Set(types.ResourceSubscriptionsSessionKey, subs)
	return nil
}

func (d *Data) Sync(ctx context.Context, defaultConfig types.ConfigFactory) error {
	var (
		session      = mcp.SessionFromContext(ctx)
		existingHash string
		nctx         = types.NanobotContext(ctx)
	)

	if nctx.User.ID != "" {
		session.Set(types.AccountIDSessionKey, nctx.User.ID)
	}

	initSubscriptions(session)

	d.setURL(ctx)

	config, err := d.getAndSetConfig(ctx, defaultConfig)
	if err != nil {
		return err
	}

	session.Get(types.ConfigHashSessionKey, &existingHash)

	digest := sha256.New()
	_ = json.NewEncoder(digest).Encode(struct {
		Config types.Config      `json:"config"`
		Env    map[string]string `json:"env"`
	}{
		Config: config,
		Env:    session.GetEnvMap(),
	})
	hash := fmt.Sprintf("%x", digest.Sum(nil))

	if hash != existingHash {
		d.Refresh(ctx, true)
	}

	session.Set(types.ConfigHashSessionKey, mcp.SavedString(hash))
	return nil
}

func (d *Data) Refresh(ctx context.Context, close bool) {
	session := mcp.SessionFromContext(ctx)

	if close {
		for key, value := range session.Attributes() {
			if !strings.HasPrefix(key, "clients/") {
				continue
			}
			if closer, ok := value.(interface{ Close(bool) }); ok {
				closer.Close(false)
			}
			session.Delete(key)
		}
	}

	session.Delete(toolMappingKey)
	session.Delete(types.CurrentAgentSessionKey)
	session.Delete(promptMappingKey)
	session.Delete(resourceMappingKey)
	session.Delete(resourceTemplateMappingKey)
	session.Delete(agentsSessionKey)
	session.Delete(currentAgentTargetSessionKey)
}

func (d *Data) getPublishedMCPServers(ctx context.Context) (result []string) {
	var (
		c       types.Config
		session = mcp.SessionFromContext(ctx)
	)
	session.Get(types.ConfigSessionKey, &c)

	for _, e := range c.Publish.Entrypoint {
		if _, ok := c.Agents[e]; ok {
			result = append(result, e)
		}
	}

	result = append(result, c.Publish.MCPServers...)
	return result
}

func (d *Data) InitializedClient(ctx context.Context, name string) (*mcp.Client, error) {
	return d.runtime.GetClient(ctx, name)
}

func (d *Data) ToolMapping(ctx context.Context, opts ...GetOption) (types.ToolMappings, error) {
	var (
		session      = mcp.SessionFromContext(ctx)
		toolMappings = types.ToolMappings{}
		opt          = complete.Complete(opts...)
	)

	if !opt.ForceFetch {
		if found := session.Get(toolMappingKey, &toolMappings); !found && opt.AllowMissing {
			return nil, nil
		} else if found {
			return toolMappings, nil
		}
	}

	var c types.Config
	session.Get(types.ConfigSessionKey, &c)

	toolMappings, err := d.runtime.BuildToolMappings(ctx, append(d.getPublishedMCPServers(ctx), c.Publish.Tools...))
	if err != nil {
		return nil, err
	}

	toolMappings = schema.ValidateToolMappings(toolMappings)
	session.Set(toolMappingKey, toolMappings)

	return toolMappings, nil
}

func (d *Data) PublishedResourceTemplateMappings(ctx context.Context, opts ...GetOption) (types.ResourceTemplateMappings, error) {
	var (
		resourceTemplates = types.ResourceTemplateMappings{}
		session           = mcp.SessionFromContext(ctx)
		c                 types.Config
	)

	if found := session.Get(resourceTemplateMappingKey, &resourceTemplates); !found && complete.Complete(opts...).AllowMissing {
		return nil, nil
	} else if found {
		return resourceTemplates, nil
	}

	session.Get(types.ConfigSessionKey, &c)

	resourceTemplateMappings, err := d.BuildResourceTemplateMappings(ctx, append(d.getPublishedMCPServers(ctx), c.Publish.ResourceTemplates...))
	if err != nil {
		return nil, err
	}
	session.Set(resourceTemplateMappingKey, resourceTemplateMappings)

	return resourceTemplateMappings, nil
}

var ErrResourceNotFound = errors.New("resource not found")

type resourceTemplateMatchCache map[string]struct {
	MCPServer  string `json:"m,omitempty"`
	TargetName string `json:"t,omitempty"`
}

func (r resourceTemplateMatchCache) Deserialize(v any) (any, error) {
	r = resourceTemplateMatchCache{}
	return r, mcp.JSONCoerce(v, &r)
}

func (r *resourceTemplateMatchCache) Serialize(v any) (any, error) {
	return r, nil
}

func (d *Data) checkResourceMatch(ctx context.Context, uri, keySuffix string) (string, string, bool) {
	var (
		agent   = types.CurrentAgent(ctx)
		session = mcp.SessionFromContext(ctx)
		cache   = resourceTemplateMatchCache{}
		key     = fmt.Sprintf("%s::%s", agent, uri) + keySuffix
	)
	session.Get(resourceTemplateMappingCacheKey, &cache)
	if hit, ok := cache[key]; ok {
		return hit.MCPServer, hit.TargetName, true
	}
	return "", "", false
}

func (d *Data) cacheResourceMatch(ctx context.Context, uri, server, resourceName string) {
	var (
		agent   = types.CurrentAgent(ctx)
		session = mcp.SessionFromContext(ctx)
		cache   = resourceTemplateMatchCache{}
		key     = fmt.Sprintf("%s::%s", agent, uri)
	)
	session.Get(resourceTemplateMappingCacheKey, &cache)
	cache[key] = struct {
		MCPServer  string `json:"m,omitempty"`
		TargetName string `json:"t,omitempty"`
	}{
		MCPServer:  server,
		TargetName: resourceName,
	}
	session.Set(resourceTemplateMappingCacheKey, &cache)
}

func (d *Data) MatchPublishedResource(ctx context.Context, uri string) (retServer string, retResourceName string, retErr error) {
	var ok bool
	if retServer, retResourceName, ok = d.checkResourceMatch(ctx, uri, ""); ok {
		return
	}

	defer func() {
		if retErr != nil {
			return
		}
		d.cacheResourceMatch(ctx, uri, retServer, retResourceName)
	}()

	resourceMappings, err := d.PublishedResourceMappings(ctx)
	if err != nil {
		return "", "", err
	}

	resourceMapping, ok := resourceMappings[uri]
	if ok {
		return resourceMapping.MCPServer, uri, nil
	}

	resourceTemplateMappings, err := d.PublishedResourceTemplateMappings(ctx)
	if err != nil {
		return "", "", err
	}

	templateMatch, resourceName, ok := d.matchResourceURITemplate(resourceTemplateMappings, uri)
	if !ok {
		return "", "", fmt.Errorf("resource %q not found: %w", uri, ErrResourceNotFound)
	}

	return templateMatch.MCPServer, resourceName, nil
}

func (d *Data) filterSupportingResources(ctx context.Context, refs []string) (result []string, _ error) {
	for _, ref := range refs {
		toolRef := types.ParseToolRef(ref)
		if toolRef.Server == "" {
			continue
		}

		client, err := d.runtime.GetClient(ctx, toolRef.Server)
		if err != nil {
			return nil, err
		}

		if client.Session.InitializeResult.Capabilities.Resources != nil {
			result = append(result, refs...)
		}
	}

	return
}

func (d *Data) MatchResource(ctx context.Context, uri string, refs []string) (retServer string, retResourceName string, retErr error) {
	var ok bool
	if retServer, retResourceName, ok = d.checkResourceMatch(ctx, uri, ":"+strings.Join(refs, ",")); ok {
		return
	}

	refs, err := d.filterSupportingResources(ctx, refs)
	if err != nil {
		return "", "", fmt.Errorf("failed to filter supporting resources: %w", err)
	}

	if len(refs) == 1 {
		target := types.ParseToolRef(refs[0])
		if target.Server != "" {
			return target.Server, uri, nil
		}
	}

	defer func() {
		if retErr != nil {
			return
		}
		d.cacheResourceMatch(ctx, uri, retServer, retResourceName)
	}()

	resourceTemplateMappings, err := d.BuildResourceTemplateMappings(ctx, refs)
	if err != nil {
		return "", "", err
	}

	templateMatch, resourceName, ok := d.matchResourceURITemplate(resourceTemplateMappings, uri)
	if ok {
		return templateMatch.MCPServer, resourceName, nil
	}

	resourceMappings, err := d.BuildResourceMappings(ctx, refs)
	if err != nil {
		return "", "", err
	}

	resourceMapping, ok := resourceMappings[uri]
	if ok {
		return resourceMapping.MCPServer, uri, nil
	}

	return "", "", fmt.Errorf("resource %q not found: %w", uri, ErrResourceNotFound)
}

func (d *Data) PublishedResourceMappings(ctx context.Context) (types.ResourceMappings, error) {
	var (
		session = mcp.SessionFromContext(ctx)
		c       types.Config
	)

	session.Get(types.ConfigSessionKey, &c)

	return d.BuildResourceMappings(ctx, append(d.getPublishedMCPServers(ctx), c.Publish.Resources...))
}

func (d *Data) PublishedPromptMappings(ctx context.Context, opts ...GetOption) (types.PromptMappings, error) {
	var (
		prompts = types.PromptMappings{}
		session = mcp.SessionFromContext(ctx)
		c       = types.ConfigFromContext(ctx)
	)

	if found := session.Get(promptMappingKey, &prompts); !found && complete.Complete(opts...).AllowMissing {
		return nil, nil
	} else if found {
		return prompts, nil
	}

	promptMappings, err := d.BuildPromptMappings(ctx, append(d.getPublishedMCPServers(ctx), c.Publish.Prompts...))
	if err != nil {
		return nil, err
	}

	session.Set(promptMappingKey, promptMappings)
	return promptMappings, nil
}

func (d *Data) BuildPromptMappings(ctx context.Context, refs []string) (types.PromptMappings, error) {
	var (
		serverPrompts = map[string]*mcp.ListPromptsResult{}
		result        = types.PromptMappings{}
		c             = types.ConfigFromContext(ctx)
	)

	for _, ref := range refs {
		toolRef := types.ParseToolRef(ref)
		if toolRef.Server == "" {
			continue
		}

		if inlinePrompt, ok := c.Prompts[toolRef.Server]; ok && toolRef.Tool == "" {
			result[toolRef.PublishedName(toolRef.Server)] = types.TargetMapping[mcp.Prompt]{
				MCPServer:  toolRef.Server,
				TargetName: toolRef.Server,
				Target:     inlinePrompt.ToPrompt(toolRef.PublishedName(toolRef.Server)),
			}
			continue
		}

		prompts, ok := serverPrompts[toolRef.Server]
		if !ok {
			c, err := d.runtime.GetClient(ctx, toolRef.Server)
			if err != nil {
				return nil, err
			}
			prompts, err = c.ListPrompts(ctx)
			if err != nil {
				return nil, fmt.Errorf("failed to get prompts for server %s: %w", toolRef, err)
			}
			serverPrompts[toolRef.Server] = prompts
		}

		for _, prompt := range prompts.Prompts {
			if prompt.Name == toolRef.Tool || toolRef.Tool == "" {
				prompt.Name = toolRef.PublishedName(prompt.Name)
				result[toolRef.PublishedName(prompt.Name)] = types.TargetMapping[mcp.Prompt]{
					MCPServer:  toolRef.Server,
					TargetName: prompt.Name,
					Target:     prompt,
				}
			}
		}
	}

	return result, nil
}

func (d *Data) BuildResourceMappings(ctx context.Context, refs []string) (types.ResourceMappings, error) {
	resourceMappings := types.ResourceMappings{}
	for _, ref := range refs {
		toolRef := types.ParseToolRef(ref)
		if toolRef.Server == "" {
			continue
		}

		c, err := d.runtime.GetClient(ctx, toolRef.Server)
		if err != nil {
			slog.Error("failed to get client while building resource mappings, skipping", "server", toolRef.Server, "error", err)
			continue
		}
		resources, err := c.ListResources(ctx)
		if err != nil {
			slog.Error("failed to get resources while building resource mappings, skipping", "server", toolRef.Server, "error", err)
			continue
		}

		for _, resource := range resources.Resources {
			resourceMappings[toolRef.PublishedName(resource.URI)] = types.TargetMapping[mcp.Resource]{
				MCPServer:  toolRef.Server,
				TargetName: resource.URI,
				Target:     resource,
			}
		}
	}

	return resourceMappings, nil
}

func (d *Data) BuildResourceTemplateMappings(ctx context.Context, refs []string) (types.ResourceTemplateMappings, error) {
	resourceTemplateMappings := types.ResourceTemplateMappings{}
	for _, ref := range refs {
		toolRef := types.ParseToolRef(ref)
		if toolRef.Server == "" {
			continue
		}

		c, err := d.runtime.GetClient(ctx, toolRef.Server)
		if err != nil {
			slog.Error("failed to get client while building resource template mappings, skipping", "server", toolRef.Server, "error", err)
			continue
		}
		resources, err := c.ListResourceTemplates(ctx)
		if err != nil {
			slog.Error("failed to get resource templates while building resource template mappings, skipping", "server", toolRef.Server, "error", err)
		}

		for _, resource := range resources.ResourceTemplates {
			re, err := uriToRegexp(resource.URITemplate)
			if err != nil {
				slog.Error("failed to convert uri to regexp", "error", err)
				continue
			}
			resourceTemplateMappings[toolRef.PublishedName(resource.URITemplate)] = types.TargetMapping[types.TemplateMatch]{
				MCPServer:  toolRef.Server,
				TargetName: resource.URITemplate,
				Target: types.TemplateMatch{
					Regexp:           re,
					ResourceTemplate: resource,
				},
			}
		}
	}

	return resourceTemplateMappings, nil
}

func (d *Data) matchResourceURITemplate(resourceTemplateMappings types.ResourceTemplateMappings, uri string) (*types.TargetMapping[types.TemplateMatch], string, bool) {
	keys := slices.Sorted(maps.Keys(resourceTemplateMappings))
	for _, key := range keys {
		mapping := resourceTemplateMappings[key]
		if mapping.Target.Regexp.MatchString(uri) {
			return &mapping, uri, true
		}
	}
	return nil, "", false
}
