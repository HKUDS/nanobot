/**
 * nanobot Channels Page JavaScript
 */

let allChannels = [];
let currentConfig = {};

// Channel metadata information
const channelInfo = {
    'telegram': { icon: 'bi-telegram', color: 'primary', description: 'Telegram bot integration. Requires bot token from @BotFather.' },
    'discord': { icon: 'bi-discord', color: 'secondary', description: 'Discord bot integration. Requires bot token.' },
    'whatsapp': { icon: 'bi-whatsapp', color: 'success', description: 'WhatsApp integration via QR code login.' },
    'weixin': { icon: 'bi-wechat', color: 'success', description: 'WeChat (微信) integration via QR code login.' },
    'feishu': { icon: 'bi-box', color: 'primary', description: 'Feishu (飞书) integration using WebSocket.' },
    'dingtalk': { icon: 'bi-chat-square-text', color: 'primary', description: 'DingTalk (钉钉) integration using Stream Mode.' },
    'slack': { icon: 'bi-slack', color: 'danger', description: 'Slack integration using Socket Mode.' },
    'matrix': { icon: 'bi-chat-square', color: 'info', description: 'Matrix (Element) integration.' },
    'email': { icon: 'bi-envelope', color: 'warning', description: 'Email integration via IMAP/SMTP.' },
    'qq': { icon: 'bi-chat-dots', color: 'primary', description: 'QQ bot integration.' },
    'wecom': { icon: 'bi-building', color: 'primary', description: 'WeCom (企业微信) bot integration.' },
    'mochat': { icon: 'bi-chat-heart', color: 'success', description: 'MoChat (Claw IM) integration.' },
};

document.addEventListener('DOMContentLoaded', function() {
    loadChannels();
    setupSidebarToggle();
});

async function loadChannels() {
    try {
        const response = await api.get('/api/channels');
        allChannels = response.channels;
        currentConfig = await api.get('/api/config');
        renderChannels();
    } catch (error) {
        console.error('Failed to load channels:', error);
        showToast('Failed to load channels', 'danger');
    }
}

function renderChannels() {
    const container = document.getElementById('channelsList');
    container.innerHTML = '';
    
    if (allChannels.length === 0) {
        container.innerHTML = `
            <div class="col-12 text-center py-5">
                <i class="bi bi-plug display-1 text-muted mb-3"></i>
                <h5>No channels available</h5>
                <p class="text-muted">Channel plugins will appear here when installed</p>
            </div>
        `;
        return;
    }
    allChannels.forEach(channel => {
        const info = channelInfo[channel.name] || { icon: 'bi-plug', color: 'secondary', description: channel.display_name };
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        const statusClass = channel.enabled ? 'border-success' : '';
        const statusBadge = channel.enabled ? '<span class="badge bg-success">✓ Enabled</span>' : '<span class="badge bg-secondary">✗ Disabled</span>';
        col.innerHTML = `
            <div class="card h-100 shadow-sm ${statusClass}">
                <div class="card-header bg-white d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-center">
                        <i class="bi ${info.icon} display-5 text-${info.color} me-3"></i>
                        <div>
                            <h6 class="mb-0">${channel.display_name}</h6>
                            <small class="text-muted">${info.description.substring(0, 50)}...</small>
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <div class="mb-3">${statusBadge}</div>
                    <p class="card-text small text-muted mb-3">${info.description}</p>
                </div>
                <div class="card-footer bg-white">
                    <button class="btn btn-sm btn-primary w-100" onclick="editChannel('${channel.name}')">
                        <i class="bi bi-gear me-1"></i>Configure
                    </button>
                </div>
            </div>
        `;
        container.appendChild(col);
    });
}

function editChannel(channelName) {
    const channel = allChannels.find(c => c.name === channelName);
    if (!channel) return;
    const channelFields = {
        'telegram': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'token', type: 'password', label: 'Bot Token', placeholder: 'Bot token from @BotFather' },
            { name: 'allowFrom', type: 'text', label: 'Allowed User IDs', placeholder: 'User IDs (comma-separated), * for all' },
        ],
        'discord': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'token', type: 'password', label: 'Bot Token', placeholder: 'Discord bot token' },
            { name: 'allowFrom', type: 'text', label: 'Allowed User IDs', placeholder: 'User IDs (comma-separated)' },
            { name: 'groupPolicy', type: 'select', label: 'Group Policy', options: ['mention', 'open'], default: 'mention' },
        ],
        'whatsapp': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'allowFrom', type: 'text', label: 'Allowed Phone Numbers', placeholder: 'Phone numbers (comma-separated), * for all' },
        ],
        'feishu': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'appId', type: 'text', label: 'App ID', placeholder: 'cli_xxx' },
            { name: 'appSecret', type: 'password', label: 'App Secret', placeholder: 'App secret' },
            { name: 'allowFrom', type: 'text', label: 'Allowed User IDs', placeholder: 'Open IDs, use * for all' },
        ],
        'slack': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'botToken', type: 'password', label: 'Bot Token', placeholder: 'xoxb-...' },
            { name: 'appToken', type: 'password', label: 'App-Level Token', placeholder: 'xapp-...' },
        ],
        'email': [
            { name: 'enabled', type: 'boolean', label: 'Enabled', default: false },
            { name: 'imapHost', type: 'text', label: 'IMAP Host', placeholder: 'imap.gmail.com' },
            { name: 'imapUsername', type: 'text', label: 'IMAP Username', placeholder: 'your-email@gmail.com' },
            { name: 'imapPassword', type: 'password', label: 'IMAP Password', placeholder: 'App password' },
            { name: 'smtpHost', type: 'text', label: 'SMTP Host', placeholder: 'smtp.gmail.com' },
            { name: 'smtpUsername', type: 'text', label: 'SMTP Username', placeholder: 'your-email@gmail.com' },
            { name: 'smtpPassword', type: 'password', label: 'SMTP Password', placeholder: 'App password' },
        ],
    };
    const fields = channelFields[channelName] || [];
    document.getElementById('channelName').value = channelName;
    document.getElementById('channelConfigTitle').textContent = `Configure ${channel.display_name}`;
    document.getElementById('channelDescription').textContent = channelInfo[channelName]?.description || channel.display_name;
    const fieldsContainer = document.getElementById('channelConfigFields');
    fieldsContainer.innerHTML = '';
    const channelConfig = currentConfig.channels?.[channelName] || {};
    fields.forEach(field => {
        const value = channelConfig[field.name] !== undefined ? channelConfig[field.name] : field.default;
        let inputHtml = '';
        if (field.type === 'boolean') {
            inputHtml = `<div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="field_${field.name}" ${value ? 'checked' : ''}>
                <label class="form-check-label" for="field_${field.name}">${field.label}</label>
            </div>`;
        } else if (field.type === 'select') {
            inputHtml = `<select class="form-select" id="field_${field.name}">
                ${field.options.map(opt => `<option value="${opt}" ${value === opt ? 'selected' : ''}>${opt}</option>`).join('')}
            </select>`;
        } else {
            inputHtml = `<input type="${field.type}" class="form-control" id="field_${field.name}"
                placeholder="${field.placeholder || ''}" value="${value || ''}">`;
        }
        const formGroup = document.createElement('div');
        formGroup.className = 'mb-3';
        formGroup.innerHTML = `<label class="form-label" for="field_${field.name}">${field.label}</label>${inputHtml}`;
        fieldsContainer.appendChild(formGroup);
    });
    const modal = new bootstrap.Modal(document.getElementById('channelConfigModal'));
    modal.show();
}

async function saveChannelConfig() {
    const channelName = document.getElementById('channelName').value;
    const channel = allChannels.find(c => c.name === channelName);
    if (!channel) return;
    const config = {};
    const formFields = document.getElementById('channelConfigFields').querySelectorAll('[id^="field_"]');
    formFields.forEach(field => {
        const fieldName = field.id.replace('field_', '');
        if (field.type === 'checkbox') {
            config[fieldName] = field.checked;
        } else if (field.tagName === 'SELECT') {
            config[fieldName] = field.value;
        } else {
            config[fieldName] = field.value;
        }
    });
    try {
        const currentConfig = await api.get('/api/config');
        if (!currentConfig.channels) currentConfig.channels = {};
        currentConfig.channels[channelName] = config;
        await api.post('/api/config', currentConfig);
        showToast(`${channel.display_name} configuration saved`, 'success');
        const modal = bootstrap.Modal.getInstance(document.getElementById('channelConfigModal'));
        modal.hide();
        loadChannels();
    } catch (error) {
        console.error('Failed to save channel config:', error);
        showToast('Failed to save configuration', 'danger');
    }
}

function setupSidebarToggle() {
    document.getElementById('sidebarToggle').addEventListener('click', function() {
        document.getElementById('sidebar-wrapper').classList.toggle('collapsed');
    });
}
