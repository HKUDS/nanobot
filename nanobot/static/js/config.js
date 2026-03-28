/**
 * nanobot Configuration Page JavaScript
 */

let currentConfig = {};
let providers = [];

document.addEventListener('DOMContentLoaded', function() {
    loadProviders();
    loadConfig();
    setupSidebarToggle();
});

async function loadProviders() {
    try {
        const response = await api.get('/api/providers');
        providers = response.providers;
        const providerSelect = document.getElementById('agentProvider');
        providers.forEach(p => {
            const option = document.createElement('option');
            option.value = p.name;
            option.textContent = p.display_name;
            providerSelect.appendChild(option);
        });
        renderProviders();
    } catch (error) {
        console.error('Failed to load providers:', error);
        showToast('Failed to load providers', 'danger');
    }
}

function renderProviders() {
    const container = document.getElementById('providersContainer');
    container.innerHTML = '';

    providers.forEach(provider => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        const isOauth = provider.is_oauth;
        const isLocal = provider.is_local;
        let fields = '';
        if (isOauth) {
            fields = `
                <div class="alert alert-warning mb-2">
                    <small><i class="bi bi-shield-lock me-1"></i>OAuth provider - configure via CLI</small>
                </div>
            `;
        } else {
            fields = `
                <div class="mb-2">
                    <label class="form-label small">API Key</label>
                    <input type="password" class="form-control form-control-sm"
                           id="provider_${provider.name}_key"
                           placeholder="sk-...">
                </div>
            `;
            if (isLocal || provider.name === 'custom' || provider.name === 'vllm' || provider.name === 'ollama') {
                fields += `
                    <div class="mb-2">
                        <label class="form-label small">API Base URL</label>
                        <input type="text" class="form-control form-control-sm"
                               id="provider_${provider.name}_base"
                               placeholder="${provider.default_api_base || 'http://localhost:11434'}">
                    </div>
                `;
            }
        }
        col.innerHTML = `
            <div class="card h-100">
                <div class="card-header bg-white d-flex justify-content-between align-items-center">
                    <strong>${provider.display_name}</strong>
                    <span class="badge ${isOauth ? 'bg-warning' : isLocal ? 'bg-info' : 'bg-primary'}">
                        ${isOauth ? 'OAuth' : isLocal ? 'Local' : 'API'}
                    </span>
                </div>
                <div class="card-body">
                    ${fields}
                </div>
            </div>
        `;
        container.appendChild(col);
    });
}

async function loadConfig() {
    try {
        const response = await api.get('/api/config');
        currentConfig = response;
        if (response.agents?.defaults) {
            const defaults = response.agents.defaults;
            document.getElementById('agentModel').value = defaults.model || '';
            document.getElementById('agentProvider').value = defaults.provider || 'auto';
            document.getElementById('maxTokens').value = defaults.max_tokens || 8192;
            document.getElementById('contextWindow').value = defaults.context_window_tokens || 65536;
            document.getElementById('temperature').value = defaults.temperature || 0.1;
            document.getElementById('maxToolIterations').value = defaults.max_tool_iterations || 40;
            document.getElementById('reasoningEffort').value = defaults.reasoning_effort || '';
            document.getElementById('timezone').value = defaults.timezone || 'UTC';
        }
        if (response.gateway) {
            document.getElementById('gatewayPort').value = response.gateway.port || 18790;
            document.getElementById('heartbeatEnabled').value = response.gateway.heartbeat?.enabled ? 'true' : 'false';
            document.getElementById('heartbeatInterval').value = response.gateway.heartbeat?.interval_s || 1800;
        }
        if (response.tools?.web?.search) {
            const search = response.tools.web.search;
            document.getElementById('searchProvider').value = search.provider || 'brave';
            document.getElementById('searchApiKey').value = search.api_key || '';
            document.getElementById('searchBaseUrl').value = search.base_url || '';
            document.getElementById('maxResults').value = search.max_results || 5;
        }
        if (response.tools?.web?.proxy) {
            document.getElementById('webProxy').value = response.tools.web.proxy;
        }
        if (response.tools?.exec) {
            document.getElementById('execEnable').value = response.tools.exec.enable ? 'true' : 'false';
            document.getElementById('execTimeout').value = response.tools.exec.timeout || 60;
        }
        document.getElementById('restrictToWorkspace').checked = response.tools?.restrict_to_workspace || false;
        if (response.providers) {
            providers.forEach(provider => {
                const providerConfig = response.providers[provider.name];
                if (providerConfig) {
                    const keyInput = document.getElementById(`provider_${provider.name}_key`);
                    if (keyInput && providerConfig.api_key) {
                        keyInput.value = providerConfig.api_key;
                    }
                    const baseInput = document.getElementById(`provider_${provider.name}_base`);
                    if (baseInput && providerConfig.api_base) {
                        baseInput.value = providerConfig.api_base;
                    }
                }
            });
        }
        showToast('Configuration loaded', 'success');
    } catch (error) {
        console.error('Failed to load config:', error);
        showToast('Failed to load configuration', 'danger');
    }
}

async function saveConfig(event) {
    event.preventDefault();
    const config = {
        agents: {
            defaults: {
                model: document.getElementById('agentModel').value,
                provider: document.getElementById('agentProvider').value,
                max_tokens: parseInt(document.getElementById('maxTokens').value),
                context_window_tokens: parseInt(document.getElementById('contextWindow').value),
                temperature: parseFloat(document.getElementById('temperature').value),
                max_tool_iterations: parseInt(document.getElementById('maxToolIterations').value),
                reasoning_effort: document.getElementById('reasoningEffort').value || null,
                timezone: document.getElementById('timezone').value,
            }
        },
        gateway: {
            port: parseInt(document.getElementById('gatewayPort').value),
            heartbeat: {
                enabled: document.getElementById('heartbeatEnabled').value === 'true',
                interval_s: parseInt(document.getElementById('heartbeatInterval').value),
            }
        },
        tools: {
            web: {
                search: {
                    provider: document.getElementById('searchProvider').value,
                    api_key: document.getElementById('searchApiKey').value,
                    base_url: document.getElementById('searchBaseUrl').value,
                    max_results: parseInt(document.getElementById('maxResults').value),
                },
                proxy: document.getElementById('webProxy').value || null,
            },
            exec: {
                enable: document.getElementById('execEnable').value === 'true',
                timeout: parseInt(document.getElementById('execTimeout').value),
            },
            restrict_to_workspace: document.getElementById('restrictToWorkspace').checked,
        },
        providers: {}
    };
    providers.forEach(provider => {
        const keyInput = document.getElementById(`provider_${provider.name}_key`);
        const baseInput = document.getElementById(`provider_${provider.name}_base`);
        if (keyInput || baseInput) {
            config.providers[provider.name] = {};
            if (keyInput && keyInput.value) {
                config.providers[provider.name].api_key = keyInput.value;
            }
            if (baseInput && baseInput.value) {
                config.providers[provider.name].api_base = baseInput.value;
            }
        }
    });
    try {
        const result = await api.post('/api/config', config);
        showToast('Configuration saved successfully', 'success');
    } catch (error) {
        console.error('Failed to save config:', error);
        showToast('Failed to save configuration', 'danger');
    }
}

async function resetToDefaults() {
    if (!confirm('Are you sure you want to reset to default configuration? This will overwrite your current settings.')) {
        return;
    }
    document.getElementById('agentModel').value = 'anthropic/claude-opus-4-5';
    document.getElementById('agentProvider').value = 'auto';
    document.getElementById('maxTokens').value = 8192;
    document.getElementById('contextWindow').value = 65536;
    document.getElementById('temperature').value = 0.1;
    document.getElementById('maxToolIterations').value = 40;
    document.getElementById('reasoningEffort').value = '';
    document.getElementById('timezone').value = 'UTC';
    document.getElementById('gatewayPort').value = 18790;
    document.getElementById('heartbeatEnabled').value = 'true';
    document.getElementById('heartbeatInterval').value = 1800;
    document.getElementById('searchProvider').value = 'brave';
    document.getElementById('maxResults').value = 5;
    document.getElementById('execEnable').value = 'true';
    document.getElementById('execTimeout').value = 60;
    document.getElementById('restrictToWorkspace').checked = false;
    showToast('Form reset to defaults. Click Save to apply.', 'info');
}

function setupSidebarToggle() {
    document.getElementById('sidebarToggle').addEventListener('click', function() {
        document.getElementById('sidebar-wrapper').classList.toggle('collapsed');
    });
}
