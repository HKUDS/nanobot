/**
 * nanobot Status Page JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    loadStatus();
    setupSidebarToggle();
});

async function loadStatus() {
    try {
        const status = await api.get('/api/status');
        updateOverview(status);
        updateProvidersList(status.providers);
        updateChannelsList(status.channels);
        showToast('Status refreshed', 'success');
    } catch (error) {
        console.error('Failed to load status:', error);
        showToast('Failed to load status', 'danger');
    }
}

function updateOverview(status) {
    document.getElementById('configStatus').className = `badge ${status.config_exists ? 'bg-success' : 'bg-danger'}`;
    document.getElementById('configStatus').textContent = status.config_exists ? '✓ Configured' : '✗ Missing';
    document.getElementById('workspaceStatus').className = `badge ${status.workspace_exists ? 'bg-success' : 'bg-danger'}`;
    document.getElementById('workspaceStatus').textContent = status.workspace_exists ? '✓ Active' : '✗ Missing';
    const configuredProviders = Object.values(status.providers || {}).filter(p => p.configured).length;
    const totalProviders = Object.keys(status.providers || {}).length;
    document.getElementById('providersStatus').className = 'badge bg-info';
    document.getElementById('providersStatus').textContent = `${configuredProviders}/${totalProviders} Configured`;
    const enabledChannels = Object.values(status.channels || {}).filter(c => c.enabled).length;
    const totalChannels = Object.keys(status.channels || {}).length;
    document.getElementById('channelsStatus').className = 'badge bg-warning';
    document.getElementById('channelsStatus').textContent = `${enabledChannels}/${totalChannels} Enabled`;
}

function updateProvidersList(providers) {
    const container = document.getElementById('providersList');
    container.innerHTML = '';
    if (Object.keys(providers).length === 0) {
        container.innerHTML = '<p class="text-muted text-center">No providers configured</p>';
        return;
    }
    const providerNames = {
        'custom': 'Custom/OpenAI Compatible', 'azure_openai': 'Azure OpenAI', 'anthropic': 'Anthropic',
        'openai': 'OpenAI', 'openrouter': 'OpenRouter', 'deepseek': 'DeepSeek', 'groq': 'Groq',
        'zhipu': 'Zhipu', 'dashscope': 'DashScope', 'vllm': 'vLLM', 'ollama': 'Ollama',
        'ovms': 'OVMS', 'gemini': 'Gemini', 'moonshot': 'Moonshot', 'minimax': 'MiniMax',
        'mistral': 'Mistral', 'stepfun': 'StepFun', 'aihubmix': 'AiHubMix', 'siliconflow': 'SiliconFlow',
        'volcengine': 'VolcEngine',
    };
    for (const [name, info] of Object.entries(providers)) {
        const div = document.createElement('div');
        div.className = 'd-flex justify-content-between align-items-center py-2 border-bottom';
        let typeBadge = info.status === 'oauth' ? '<span class="badge bg-warning">OAuth</span>' :
                        info.status === 'local' ? '<span class="badge bg-info">Local</span>' :
                        '<span class="badge bg-primary">API Key</span>';
        let statusBadge = info.configured ? '<span class="badge bg-success">✓</span>' :
                                            '<span class="badge bg-danger">✗</span>';
        div.innerHTML = `
            <div>
                <strong>${providerNames[name] || name}</strong>
                <span class="ms-2">${typeBadge}</span>
            </div>
            ${statusBadge}
        `;
        container.appendChild(div);
    }
}

function updateChannelsList(channels) {
    const container = document.getElementById('channelsList');
    container.innerHTML = '';
    if (Object.keys(channels).length === 0) {
        container.innerHTML = '<p class="text-muted text-center">No channels configured</p>';
        return;
    }
    const channelNames = {
        'telegram': 'Telegram', 'discord': 'Discord', 'whatsapp': 'WhatsApp', 'weixin': 'WeChat',
        'feishu': 'Feishu', 'dingtalk': 'DingTalk', 'slack': 'Slack', 'matrix': 'Matrix',
        'email': 'Email', 'qq': 'QQ', 'wecom': 'WeCom', 'mochat': 'MoChat',
    };
    for (const [name, info] of Object.entries(channels)) {
        const div = document.createElement('div');
        div.className = 'd-flex justify-content-between align-items-center py-2 border-bottom';
        const statusBadge = info.enabled ? '<span class="badge bg-success">✓ Enabled</span>' :
                                           '<span class="badge bg-secondary">✗ Disabled</span>';
        div.innerHTML = `
            <div><strong>${channelNames[name] || name}</strong></div>
            ${statusBadge}
        `;
        container.appendChild(div);
    }
}

function setupSidebarToggle() {
    document.getElementById('sidebarToggle').addEventListener('click', function() {
        document.getElementById('sidebar-wrapper').classList.toggle('collapsed');
    });
}
