/**
 * Dashboard Component
 */

const DashboardComponent = {
    template: `
        <div class="container-fluid p-4">
            <div class="row">
                <div class="col-12">
                    <h1 class="mb-4">🐈 nanobot Dashboard</h1>
                </div>
            </div>

            <div class="row g-4 mb-4">
                <div class="col-md-3">
                    <div class="card h-100 shadow-sm">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <h6 class="text-muted mb-2">Status</h6>
                                    <h4 class="mb-0">{{ status.model || '-' }}</h4>
                                </div>
                                <i class="bi bi-robot display-4 text-primary"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100 shadow-sm">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <h6 class="text-muted mb-2">Config</h6>
                                    <h4 class="mb-0">{{ status.config_exists ? '✓ Ready' : '✗ Missing' }}</h4>
                                </div>
                                <i class="bi bi-file-earmark-check display-4 text-success"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100 shadow-sm">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <h6 class="text-muted mb-2">Channels</h6>
                                    <h4 class="mb-0">{{ enabledChannels }}/{{ totalChannels }}</h4>
                                </div>
                                <i class="bi bi-plug display-4 text-info"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100 shadow-sm">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <h6 class="text-muted mb-2">Providers</h6>
                                    <h4 class="mb-0">{{ configuredProviders }}/{{ totalProviders }}</h4>
                                </div>
                                <i class="bi bi-cloud-check display-4 text-warning"></i>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row g-4 mb-4">
                <div class="col-md-6">
                    <div class="card shadow-sm">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-lightning-charge me-2"></i>Quick Actions</h5>
                        </div>
                        <div class="card-body">
                            <div class="d-grid gap-2">
                                <router-link to="/chat" class="btn btn-primary">
                                    <i class="bi bi-chat-dots me-2"></i>Chat with Agent
                                </router-link>
                                <router-link to="/config" class="btn btn-outline-primary">
                                    <i class="bi bi-gear me-2"></i>Configure nanobot
                                </router-link>
                                <router-link to="/channels" class="btn btn-outline-primary">
                                    <i class="bi bi-plug me-2"></i>Manage Channels
                                </router-link>
                                <button class="btn btn-outline-primary" @click="refreshStatus">
                                    <i class="bi bi-arrow-clockwise me-2"></i>Refresh Status
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-info-circle me-2"></i>System Info</h5>
                        </div>
                        <div class="card-body">
                            <ul class="list-unstyled mb-0">
                                <li class="py-2 border-bottom">
                                    <strong>Version:</strong> <span class="text-muted">0.1.4.post5</span>
                                </li>
                                <li class="py-2 border-bottom">
                                    <strong>Workspace:</strong> <span class="text-muted">{{ status.workspace_exists ? '✓ Active' : '✗ Not found' }}</span>
                                </li>
                                <li class="py-2">
                                    <strong>Gateway Port:</strong> <span class="text-muted">{{ status.gateway?.port || 18790 }}</span>
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row">
                <div class="col-12">
                    <div class="card shadow-sm">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-terminal me-2"></i>Quick Chat</h5>
                        </div>
                        <div class="card-body">
                            <div class="input-group">
                                <input type="text" class="form-control" v-model="quickChatMessage"
                                       placeholder="Type a message to nanobot..."
                                       @keypress="handleKeyPress"
                                       :disabled="isSending">
                                <button class="btn btn-primary" type="button" @click="sendQuickChat" :disabled="isSending">
                                    <i class="bi bi-send me-1"></i>{{ isSending ? 'Sending...' : 'Send' }}
                                </button>
                            </div>
                            <div v-if="quickChatResponse" class="mt-3">
                                <div class="alert alert-light border">
                                    <div v-html="renderedResponse"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            status: {},
            quickChatMessage: '',
            quickChatResponse: '',
            isSending: false,
            loading: false,
        };
    },
    computed: {
        enabledChannels() {
            return Object.values(this.status.channels || {}).filter(c => c.enabled).length;
        },
        totalChannels() {
            return Object.keys(this.status.channels || {}).length;
        },
        configuredProviders() {
            return Object.values(this.status.providers || {}).filter(p => p.configured).length;
        },
        totalProviders() {
            return Object.keys(this.status.providers || {}).length;
        },
        renderedResponse() {
            if (!this.quickChatResponse) return '';
            return window.marked ? marked.parse(this.quickChatResponse) : this.quickChatResponse;
        }
    },
    methods: {
        async loadStatus() {
            try {
                this.status = await api.get('/api/status');
            } catch (error) {
                console.error('Failed to load dashboard:', error);
                showToast('Failed to load dashboard data', 'danger');
            }
        },
        async refreshStatus() {
            await this.loadStatus();
            showToast('Status refreshed', 'success');
        },
        handleKeyPress(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                this.sendQuickChat();
            }
        },
        async sendQuickChat() {
            const message = this.quickChatMessage.trim();
            if (!message || this.isSending) return;

            this.isSending = true;
            this.quickChatResponse = '<div class="spinner-border spinner-border-sm me-2"></div>Thinking...';

            try {
                const controller = new AbortController();
                let fullContent = '';

                await api.streamChat(message, 'web:quick', {
                    onContent: (chunk) => {
                        fullContent += chunk;
                        this.quickChatResponse = fullContent;
                    },
                    onDone: () => {},
                    onError: (err) => { throw err; },
                    signal: controller.signal,
                });
            } catch (error) {
                this.quickChatResponse = `<div class="alert alert-danger mb-0">Error: ${escapeHtml(error.message)}</div>`;
            } finally {
                this.isSending = false;
                this.quickChatMessage = '';
            }
        }
    },
    mounted() {
        this.loadStatus();
    }
};

window.DashboardComponent = DashboardComponent;
