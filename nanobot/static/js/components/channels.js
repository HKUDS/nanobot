/**
 * Channels Management Component
 */

const ChannelsComponent = {
    template: `
        <div class="container-fluid p-4">
            <div class="row mb-4">
                <div class="col-12">
                    <h1><i class="bi bi-plug me-2"></i>Channel Management</h1>
                    <p class="text-muted">Configure and manage chat channel integrations</p>
                </div>
            </div>

            <div v-if="loading" class="row">
                <div class="col-12 text-center py-5">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </div>

            <div v-else class="row g-4">
                <div v-if="channels.length === 0" class="col-12 text-center py-5">
                    <i class="bi bi-plug display-1 text-muted mb-3"></i>
                    <h5>No channels available</h5>
                    <p class="text-muted">Channel plugins will appear here when installed</p>
                </div>

                <div v-for="channel in channels" :key="channel.name" class="col-md-6 col-lg-4">
                    <div :class="['card', 'h-100', 'shadow-sm', channel.enabled ? 'border-success' : '']">
                        <div class="card-header bg-white d-flex justify-content-between align-items-center">
                            <div class="d-flex align-items-center">
                                <i :class="['bi', channelInfo[channel.name]?.icon || 'bi-plug', 'display-5', 'me-3', 'text-' + (channelInfo[channel.name]?.color || 'secondary')]"></i>
                                <div>
                                    <h6 class="mb-0">{{ channel.display_name }}</h6>
                                    <small class="text-muted">{{ channelInfo[channel.name]?.description.substring(0, 50) }}...</small>
                                </div>
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="mb-3">
                                <span :class="['badge', channel.enabled ? 'bg-success' : 'bg-secondary']">
                                    {{ channel.enabled ? '✓ Enabled' : '✗ Disabled' }}
                                </span>
                            </div>
                            <p class="card-text small text-muted mb-3">{{ channelInfo[channel.name]?.description || channel.display_name }}</p>
                        </div>
                        <div class="card-footer bg-white">
                            <button class="btn btn-sm btn-primary w-100" @click="editChannel(channel)">
                                <i class="bi bi-gear me-1"></i>Configure
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Channel Config Modal -->
            <div class="modal fade" id="channelConfigModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Configure {{ editingChannel?.display_name }}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-info">
                                <i class="bi bi-info-circle me-2"></i>
                                {{ channelInfo[editingChannel?.name]?.description || 'Configure your channel settings below.' }}
                            </div>
                            <div v-for="field in editingFields" :key="field.name" class="mb-3">
                                <template v-if="field.type === 'boolean'">
                                    <div class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" :id="'field_' + field.name" v-model="editingValues[field.name]">
                                        <label class="form-check-label" :for="'field_' + field.name">{{ field.label }}</label>
                                    </div>
                                </template>
                                <template v-else-if="field.type === 'select'">
                                    <label class="form-label" :for="'field_' + field.name">{{ field.label }}</label>
                                    <select class="form-select" :id="'field_' + field.name" v-model="editingValues[field.name]">
                                        <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
                                    </select>
                                </template>
                                <template v-else>
                                    <label class="form-label" :for="'field_' + field.name">{{ field.label }}</label>
                                    <input :type="field.type" class="form-control" :id="'field_' + field.name"
                                           v-model="editingValues[field.name]"
                                           :placeholder="field.placeholder || ''">
                                </template>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" @click="saveChannelConfig">
                                <i class="bi bi-save me-2"></i>Save Configuration
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            channels: [],
            loading: true,
            editingChannel: null,
            editingFields: [],
            editingValues: {},
            channelInfo: {
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
            },
            channelFieldDefs: {
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
            },
            modalInstance: null,
        };
    },
    methods: {
        async loadChannels() {
            this.loading = true;
            try {
                const response = await api.get('/api/channels');
                this.channels = response.channels;
            } catch (error) {
                console.error('Failed to load channels:', error);
                showToast('Failed to load channels', 'danger');
            } finally {
                this.loading = false;
            }
        },
        editChannel(channel) {
            this.editingChannel = channel;
            this.editingFields = this.channelFieldDefs[channel.name] || [];
            // Load current config values
            const channelConfig = channel.config || {};
            this.editingValues = {};
            this.editingFields.forEach(f => {
                this.editingValues[f.name] = channelConfig[f.name] !== undefined ? channelConfig[f.name] : f.default;
            });
            // Show modal
            this.modalInstance = new bootstrap.Modal(document.getElementById('channelConfigModal'));
            this.modalInstance.show();
        },
        async saveChannelConfig() {
            if (!this.editingChannel) return;
            const channelName = this.editingChannel.name;
            const config = { ...this.editingValues };

            try {
                const currentConfig = await api.get('/api/config');
                if (!currentConfig.channels) currentConfig.channels = {};
                currentConfig.channels[channelName] = config;
                await api.post('/api/config', currentConfig);
                showToast(`${this.editingChannel.display_name} configuration saved`, 'success');
                this.modalInstance.hide();
                await this.loadChannels();
            } catch (error) {
                console.error('Failed to save channel config:', error);
                showToast('Failed to save configuration', 'danger');
            }
        }
    },
    mounted() {
        this.loadChannels();
    }
};

window.ChannelsComponent = ChannelsComponent;
