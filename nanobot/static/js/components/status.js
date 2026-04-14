/**
 * Status Component
 */

const StatusComponent = {
    template: `
        <div class="container-fluid p-4">
            <div class="row mb-4">
                <div class="col-12">
                    <h1><i class="bi bi-activity me-2"></i>System Status</h1>
                    <p class="text-muted">Monitor your nanobot instance health and configuration</p>
                </div>
            </div>

            <div class="row g-4 mb-4">
                <div class="col-md-3">
                    <div class="card shadow-sm h-100">
                        <div class="card-body text-center">
                            <i class="bi bi-file-earmark-check display-4 text-success mb-3"></i>
                            <h5>Configuration</h5>
                            <div :class="['badge', status.config_exists ? 'bg-success' : 'bg-danger']">
                                {{ status.config_exists ? '✓ Configured' : '✗ Missing' }}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card shadow-sm h-100">
                        <div class="card-body text-center">
                            <i class="bi bi-folder display-4 text-primary mb-3"></i>
                            <h5>Workspace</h5>
                            <div :class="['badge', status.workspace_exists ? 'bg-success' : 'bg-danger']">
                                {{ status.workspace_exists ? '✓ Active' : '✗ Missing' }}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card shadow-sm h-100">
                        <div class="card-body text-center">
                            <i class="bi bi-cloud display-4 text-info mb-3"></i>
                            <h5>Providers</h5>
                            <div class="badge bg-info">
                                {{ configuredProviders }}/{{ totalProviders }} Configured
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card shadow-sm h-100">
                        <div class="card-body text-center">
                            <i class="bi bi-plug display-4 text-warning mb-3"></i>
                            <h5>Channels</h5>
                            <div class="badge bg-warning">
                                {{ enabledChannels }}/{{ totalChannels }} Enabled
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card shadow-sm">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-cloud me-2"></i>Providers</h5>
                        </div>
                        <div class="card-body">
                            <div v-if="Object.keys(status.providers || {}).length === 0" class="text-center text-muted">
                                No providers configured
                            </div>
                            <div v-for="(info, name) in status.providers" :key="name"
                                 class="d-flex justify-content-between align-items-center py-2 border-bottom">
                                <div>
                                    <strong>{{ providerNames[name] || name }}</strong>
                                    <span class="ms-2">
                                        <span v-if="info.status === 'oauth'" class="badge bg-warning">OAuth</span>
                                        <span v-else-if="info.status === 'local'" class="badge bg-info">Local</span>
                                        <span v-else class="badge bg-primary">API Key</span>
                                    </span>
                                </div>
                                <span :class="['badge', info.configured ? 'bg-success' : 'bg-danger']">
                                    {{ info.configured ? '✓' : '✗' }}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-plug me-2"></i>Channels</h5>
                        </div>
                        <div class="card-body">
                            <div v-if="Object.keys(status.channels || {}).length === 0" class="text-center text-muted">
                                No channels configured
                            </div>
                            <div v-for="(info, name) in status.channels" :key="name"
                                 class="d-flex justify-content-between align-items-center py-2 border-bottom">
                                <div><strong>{{ channelNames[name] || name }}</strong></div>
                                <span :class="['badge', info.enabled ? 'bg-success' : 'bg-secondary']">
                                    {{ info.enabled ? '✓ Enabled' : '✗ Disabled' }}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mt-4">
                <div class="col-12 text-center">
                    <button class="btn btn-primary" @click="loadStatus">
                        <i class="bi bi-arrow-clockwise me-2"></i>Refresh Status
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            status: {},
            providerNames: {
                'custom': 'Custom/OpenAI Compatible', 'azure_openai': 'Azure OpenAI', 'anthropic': 'Anthropic',
                'openai': 'OpenAI', 'openrouter': 'OpenRouter', 'deepseek': 'DeepSeek', 'groq': 'Groq',
                'zhipu': 'Zhipu', 'dashscope': 'DashScope', 'vllm': 'vLLM', 'ollama': 'Ollama',
                'ovms': 'OVMS', 'gemini': 'Gemini', 'moonshot': 'Moonshot', 'minimax': 'MiniMax',
                'mistral': 'Mistral', 'stepfun': 'StepFun', 'aihubmix': 'AiHubMix', 'siliconflow': 'SiliconFlow',
                'volcengine': 'VolcEngine',
            },
            channelNames: {
                'telegram': 'Telegram', 'discord': 'Discord', 'whatsapp': 'WhatsApp', 'weixin': 'WeChat',
                'feishu': 'Feishu', 'dingtalk': 'DingTalk', 'slack': 'Slack', 'matrix': 'Matrix',
                'email': 'Email', 'qq': 'QQ', 'wecom': 'WeCom', 'mochat': 'MoChat',
            },
        };
    },
    computed: {
        configuredProviders() {
            return Object.values(this.status.providers || {}).filter(p => p.configured).length;
        },
        totalProviders() {
            return Object.keys(this.status.providers || {}).length;
        },
        enabledChannels() {
            return Object.values(this.status.channels || {}).filter(c => c.enabled).length;
        },
        totalChannels() {
            return Object.keys(this.status.channels || {}).length;
        },
    },
    methods: {
        async loadStatus() {
            try {
                this.status = await api.get('/api/status');
                showToast('Status refreshed', 'success');
            } catch (error) {
                console.error('Failed to load status:', error);
                showToast('Failed to load status', 'danger');
            }
        }
    },
    mounted() {
        this.loadStatus();
    }
};

window.StatusComponent = StatusComponent;
