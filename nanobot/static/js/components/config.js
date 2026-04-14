/**
 * Configuration Component
 */

const ConfigComponent = {
    template: `
        <div class="container-fluid p-4">
            <div class="row mb-4">
                <div class="col-12">
                    <h1><i class="bi bi-gear me-2"></i>Configuration</h1>
                    <p class="text-muted">Manage your nanobot settings, API keys, and preferences</p>
                </div>
            </div>

            <form @submit.prevent="saveConfig">
                <div class="card shadow-sm mb-4">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-cloud me-2"></i>LLM Providers</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-info">
                            <i class="bi bi-info-circle me-2"></i>
                            Configure your LLM provider API keys. At least one provider is required.
                        </div>
                        <div class="row g-3">
                            <div class="col-md-6 col-lg-4" v-for="provider in providers" :key="provider.name">
                                <div class="card h-100">
                                    <div class="card-header bg-white d-flex justify-content-between align-items-center">
                                        <strong>{{ provider.display_name }}</strong>
                                        <span :class="['badge', provider.is_oauth ? 'bg-warning' : provider.is_local ? 'bg-info' : 'bg-primary']">
                                            {{ provider.is_oauth ? 'OAuth' : provider.is_local ? 'Local' : 'API' }}
                                        </span>
                                    </div>
                                    <div class="card-body">
                                        <div v-if="provider.is_oauth" class="alert alert-warning mb-2">
                                            <small><i class="bi bi-shield-lock me-1"></i>OAuth provider - configure via CLI</small>
                                        </div>
                                        <template v-else>
                                            <div class="mb-2">
                                                <label class="form-label small">API Key</label>
                                                <input type="password" class="form-control form-control-sm"
                                                       v-model="providerConfigs[provider.name].api_key"
                                                       placeholder="sk-...">
                                            </div>
                                            <div v-if="provider.is_local || ['custom', 'vllm', 'ollama'].includes(provider.name)" class="mb-2">
                                                <label class="form-label small">API Base URL</label>
                                                <input type="text" class="form-control form-control-sm"
                                                       v-model="providerConfigs[provider.name].api_base"
                                                       :placeholder="provider.default_api_base || 'http://localhost:11434'">
                                            </div>
                                        </template>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-robot me-2"></i>Agent Settings</h5>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Default Model</label>
                                <input type="text" class="form-control" v-model="config.agents.defaults.model" placeholder="e.g., anthropic/claude-opus-4-5">
                                <div class="form-text">Format: provider/model-name</div>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Provider</label>
                                <select class="form-select" v-model="config.agents.defaults.provider">
                                    <option value="auto">Auto-detect</option>
                                    <option v-for="p in providers" :key="p.name" :value="p.name">{{ p.display_name }}</option>
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Max Tokens</label>
                                <input type="number" class="form-control" v-model.number="config.agents.defaults.max_tokens">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Context Window</label>
                                <input type="number" class="form-control" v-model.number="config.agents.defaults.context_window_tokens">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Temperature</label>
                                <input type="number" class="form-control" v-model.number="config.agents.defaults.temperature" step="0.1" min="0" max="2">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Max Tool Iterations</label>
                                <input type="number" class="form-control" v-model.number="config.agents.defaults.max_tool_iterations">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Reasoning Effort</label>
                                <select class="form-select" v-model="config.agents.defaults.reasoning_effort">
                                    <option value="">Disabled</option>
                                    <option value="low">Low</option>
                                    <option value="medium">Medium</option>
                                    <option value="high">High</option>
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Timezone</label>
                                <input type="text" class="form-control" v-model="config.agents.defaults.timezone">
                                <div class="form-text">IANA timezone format</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-server me-2"></i>Gateway Settings</h5>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Port</label>
                                <input type="number" class="form-control" v-model.number="config.gateway.port">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Heartbeat</label>
                                <select class="form-select" v-model="config.gateway.heartbeat.enabled">
                                    <option :value="true">Enabled</option>
                                    <option :value="false">Disabled</option>
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Heartbeat Interval (seconds)</label>
                                <input type="number" class="form-control" v-model.number="config.gateway.heartbeat.interval_s">
                                <div class="form-text">Default: 1800s (30 minutes)</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-search me-2"></i>Web Search</h5>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Provider</label>
                                <select class="form-select" v-model="config.tools.web.search.provider">
                                    <option value="brave">Brave</option>
                                    <option value="tavily">Tavily</option>
                                    <option value="duckduckgo">DuckDuckGo</option>
                                    <option value="searxng">SearXNG</option>
                                    <option value="jina">Jina</option>
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">API Key</label>
                                <input type="password" class="form-control" v-model="config.tools.web.search.api_key">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Max Results</label>
                                <input type="number" class="form-control" v-model.number="config.tools.web.search.max_results" min="1" max="20">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Base URL (for SearXNG)</label>
                                <input type="text" class="form-control" v-model="config.tools.web.search.base_url" placeholder="https://searxng.example.com">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Web Proxy (Optional)</label>
                                <input type="text" class="form-control" v-model="config.tools.web.proxy" placeholder="http://127.0.0.1:7890">
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-tools me-2"></i>Tools</h5>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Shell Execution</label>
                                <select class="form-select" v-model="config.tools.exec.enable">
                                    <option value="true">Enabled</option>
                                    <option value="false">Disabled</option>
                                </select>
                                <div class="form-text">Allow agent to execute shell commands</div>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Command Timeout (seconds)</label>
                                <input type="number" class="form-control" v-model.number="config.tools.exec.timeout">
                            </div>
                            <div class="col-md-12">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="restrictToWorkspace" v-model="config.tools.restrict_to_workspace">
                                    <label class="form-check-label" for="restrictToWorkspace">Restrict tools to workspace directory</label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="d-flex gap-2 mb-4">
                    <button type="submit" class="btn btn-primary btn-lg">
                        <i class="bi bi-save me-2"></i>Save Configuration
                    </button>
                    <button type="button" class="btn btn-outline-secondary" @click="loadConfig">
                        <i class="bi bi-arrow-clockwise me-2"></i>Reload
                    </button>
                    <button type="button" class="btn btn-outline-danger" @click="resetToDefaults">
                        <i class="bi bi-arrow-counterclockwise me-2"></i>Reset to Defaults
                    </button>
                </div>
            </form>
        </div>
    `,
    data() {
        return {
            config: {
                agents: { defaults: {} },
                gateway: { port: 18790, heartbeat: { enabled: true, interval_s: 1800 } },
                tools: { web: { search: {}, proxy: '' }, exec: { enable: 'true', timeout: 60 }, restrict_to_workspace: false },
                providers: {},
            },
            providers: [],
            providerConfigs: {},
        };
    },
    methods: {
        async loadProviders() {
            try {
                const response = await api.get('/api/providers');
                this.providers = response.providers;
                // Initialize provider configs
                this.providers.forEach(p => {
                    if (!this.providerConfigs[p.name]) {
                        this.providerConfigs[p.name] = { api_key: '', api_base: '' };
                    }
                });
            } catch (error) {
                console.error('Failed to load providers:', error);
                showToast('Failed to load providers', 'danger');
            }
        },
        async loadConfig() {
            try {
                const response = await api.get('/api/config');
                // Merge response into config
                this.config = {
                    agents: { defaults: { model: '', provider: 'auto', max_tokens: 8192, context_window_tokens: 65536, temperature: 0.1, max_tool_iterations: 40, reasoning_effort: '', timezone: 'UTC' }, ...response.agents?.defaults },
                    gateway: { port: 18790, heartbeat: { enabled: true, interval_s: 1800 }, ...response.gateway },
                    tools: {
                        web: { search: { provider: 'brave', api_key: '', base_url: '', max_results: 5 }, proxy: '', ...response.tools?.web },
                        exec: { enable: 'true', timeout: 60, ...response.tools?.exec },
                        restrict_to_workspace: response.tools?.restrict_to_workspace || false,
                    },
                    providers: response.providers || {},
                };
                // Fill provider configs
                if (response.providers) {
                    Object.entries(response.providers).forEach(([name, pc]) => {
                        if (this.providerConfigs[name]) {
                            this.providerConfigs[name].api_key = pc.api_key || '';
                            this.providerConfigs[name].api_base = pc.api_base || '';
                        }
                    });
                }
                showToast('Configuration loaded', 'success');
            } catch (error) {
                console.error('Failed to load config:', error);
                showToast('Failed to load configuration', 'danger');
            }
        },
        async saveConfig() {
            const configPayload = {
                agents: { defaults: this.config.agents.defaults },
                gateway: this.config.gateway,
                tools: {
                    web: {
                        search: this.config.tools.web.search,
                        proxy: this.config.tools.web.proxy || null,
                    },
                    exec: this.config.tools.exec,
                    restrict_to_workspace: this.config.tools.restrict_to_workspace,
                },
                providers: {},
            };

            // Build provider configs
            this.providers.forEach(provider => {
                const pc = this.providerConfigs[provider.name];
                if (pc && (pc.api_key || pc.api_base)) {
                    configPayload.providers[provider.name] = {};
                    if (pc.api_key) configPayload.providers[provider.name].api_key = pc.api_key;
                    if (pc.api_base) configPayload.providers[provider.name].api_base = pc.api_base;
                }
            });

            try {
                await api.post('/api/config', configPayload);
                showToast('Configuration saved successfully', 'success');
            } catch (error) {
                console.error('Failed to save config:', error);
                showToast('Failed to save configuration', 'danger');
            }
        },
        resetToDefaults() {
            if (!confirm('Are you sure you want to reset to default configuration? This will overwrite your current settings.')) return;
            this.config.agents.defaults = { model: 'anthropic/claude-opus-4-5', provider: 'auto', max_tokens: 8192, context_window_tokens: 65536, temperature: 0.1, max_tool_iterations: 40, reasoning_effort: '', timezone: 'UTC' };
            this.config.gateway = { port: 18790, heartbeat: { enabled: true, interval_s: 1800 } };
            this.config.tools.web.search = { provider: 'brave', api_key: '', base_url: '', max_results: 5 };
            this.config.tools.web.proxy = '';
            this.config.tools.exec = { enable: 'true', timeout: 60 };
            this.config.tools.restrict_to_workspace = false;
            showToast('Form reset to defaults. Click Save to apply.', 'info');
        }
    },
    mounted() {
        this.loadProviders();
        this.loadConfig();
    }
};

window.ConfigComponent = ConfigComponent;
