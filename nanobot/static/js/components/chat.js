/**
 * Chat Component with SSE Streaming
 */

const ChatComponent = {
    template: `
        <div class="container-fluid p-4 chat-container">
            <div class="row h-100">
                <div class="col-12 h-100">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-white d-flex justify-content-between align-items-center">
                            <h5 class="mb-0"><i class="bi bi-chat-dots me-2"></i>Chat with nanobot</h5>
                            <div class="ms-2">
                                <select class="form-select form-select-sm d-inline-block w-auto" v-model="selectedSession">
                                    <option value="web:default">Default Session</option>
                                    <option v-for="s in sessions" :key="s" :value="s">{{ s }}</option>
                                </select>
                                <button class="btn btn-outline-secondary btn-sm ms-2" @click="clearChat" title="Clear chat">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </div>
                        </div>
                        <div class="card-body p-0 d-flex flex-column">
                            <div ref="chatContainer" class="flex-grow-1 p-4 overflow-auto chat-messages">
                                <div v-if="messages.length === 0" class="text-center text-muted py-5">
                                    <i class="bi bi-robot display-1 mb-3"></i>
                                    <h4>Welcome to nanobot Chat</h4>
                                    <p>Start a conversation with your AI assistant</p>
                                </div>
                                <div v-for="(msg, idx) in messages" :key="idx"
                                     :class="['message', msg.role + '-message', 'mb-3']">
                                    <div :class="['d-flex align-items-start', msg.role === 'user' ? 'flex-row-reverse' : '']">
                                        <div :class="['avatar', 'rounded-circle', 'd-flex', 'align-items-center', 'justify-content-center', 'me-2', 'flex-shrink-0',
                                            msg.role === 'user' ? 'bg-primary' : 'bg-success']"
                                             style="width: 36px; height: 36px;">
                                            <i :class="['bi', msg.role === 'user' ? 'bi-person' : 'bi-robot']"></i>
                                        </div>
                                        <div :class="[msg.role === 'user' ? 'text-end' : '', 'flex-grow-1']">
                                            <div :class="['fw-bold mb-1', msg.role === 'user' ? 'text-primary' : 'text-success']">
                                                {{ msg.role === 'user' ? 'You' : 'nanobot' }}
                                                <small v-if="msg.model" class="text-muted ms-2">{{ msg.model }}</small>
                                            </div>
                                            <div :class="['message-content', msg.role === 'user' ? 'bg-primary text-white' : msg.role === 'error' ? '' : 'bg-light', 'rounded', 'p-3', 'd-inline-block']">
                                                <!-- Thinking block for assistant messages -->
                                                <div v-if="msg.role === 'assistant' && msg.thinking" class="thinking-block">
                                                    <div class="thinking-header" @click="toggleThinking(idx)">
                                                        <i :class="['bi', msg.thinkingCollapsed ? 'bi-chevron-right' : 'bi-chevron-down']"></i>
                                                        <span>Thinking</span>
                                                    </div>
                                                    <div v-show="!msg.thinkingCollapsed" class="thinking-content" v-html="renderThinking(msg.thinking)"></div>
                                                </div>
                                                <!-- Main content -->
                                                <div v-html="renderMessage(msg)"></div>
                                            </div>
                                            <div v-if="msg.role === 'assistant' && !msg.isStreaming" class="mt-2">
                                                <button class="btn btn-sm btn-link" @click="copyMessage(idx)" title="Copy">
                                                    <i :class="['bi', msg.copied ? 'bi-check' : 'bi-clipboard']"></i>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="border-top p-3 bg-light">
                                <div class="input-group">
                                    <textarea class="form-control" v-model="inputMessage" rows="2"
                                              placeholder="Type your message here... (Press Enter to send, Shift+Enter for new line)"
                                              @keydown="handleKeyPress"
                                              :disabled="isGenerating"></textarea>
                                    <button class="btn btn-primary" type="button" @click="sendMessage" v-show="!isGenerating">
                                        <i class="bi bi-send me-1"></i>Send
                                    </button>
                                    <button class="btn btn-outline-secondary" type="button" @click="stopGeneration" v-show="isGenerating">
                                        <i class="bi bi-stop-circle me-1"></i>Stop
                                    </button>
                                </div>
                                <div class="d-flex justify-content-between align-items-center mt-2">
                                    <small class="text-muted">
                                        <i class="bi bi-info-circle me-1"></i>
                                        Markdown supported • Session: <span>{{ selectedSession }}</span>
                                    </small>
                                    <div v-show="isGenerating">
                                        <span class="spinner-border spinner-border-sm me-1"></span>
                                        <span>nanobot is thinking...</span>
                                    </div>
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
            messages: [],
            inputMessage: '',
            selectedSession: 'web:default',
            isGenerating: false,
            abortController: null,
            sessions: [],
        };
    },
    methods: {
        renderMessage(msg) {
            if (msg.role === 'user') {
                return escapeHtml(msg.content);
            } else if (msg.role === 'error') {
                return `<div class="alert alert-danger mb-0">${escapeHtml(msg.content)}</div>`;
            } else if (msg.role === 'info') {
                return `<div class="alert alert-info mb-0">${escapeHtml(msg.content)}</div>`;
            } else {
                // Assistant message - render markdown
                if (!msg.content) return '<span class="text-muted">Thinking...</span>';
                return window.marked ? marked.parse(msg.content) : msg.content;
            }
        },
        renderThinking(thinking) {
            // Render thinking content as markdown
            return window.marked ? marked.parse(thinking) : escapeHtml(thinking);
        },
        toggleThinking(idx) {
            if (this.messages[idx]) {
                this.messages[idx].thinkingCollapsed = !this.messages[idx].thinkingCollapsed;
            }
        },
        handleKeyPress(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                this.sendMessage();
            }
        },
        async sendMessage() {
            const message = this.inputMessage.trim();
            if (!message || this.isGenerating) return;

            // Add user message
            this.messages.push({ role: 'user', content: message });
            this.inputMessage = '';
            this.isGenerating = true;

            // Add assistant placeholder
            const assistantIdx = this.messages.length;
            this.messages.push({ role: 'assistant', content: '', thinking: '', isStreaming: true, thinkingCollapsed: false });

            this.abortController = new AbortController();

            try {
                let fullContent = '';
                let fullThinking = '';
                let hasThinking = false;

                await api.streamChat(message, this.selectedSession, {
                    onContent: (chunk) => {
                        fullContent += chunk;
                        this.messages[assistantIdx].content = fullContent;
                        this.scrollToBottom();
                    },
                    onThinking: (chunk) => {
                        fullThinking += chunk;
                        hasThinking = true;
                        this.messages[assistantIdx].thinking = fullThinking;
                        this.scrollToBottom();
                    },
                    onDone: (metadata, thinking) => {
                        this.messages[assistantIdx].isStreaming = false;
                        if (thinking) {
                            this.messages[assistantIdx].thinking = thinking;
                            hasThinking = true;
                        }
                        if (metadata && metadata.model) {
                            this.messages[assistantIdx].model = metadata.model;
                        }
                    },
                    onError: (err) => { throw err; },
                    signal: this.abortController.signal,
                });
            } catch (error) {
                console.error('Chat error:', error);
                this.messages[assistantIdx].content = `<div class="alert alert-danger mt-2">Error: ${escapeHtml(error.message)}</div>`;
                this.messages[assistantIdx].role = 'error';
                this.messages[assistantIdx].isStreaming = false;
            } finally {
                this.isGenerating = false;
                this.abortController = null;
            }
        },
        stopGeneration() {
            if (this.abortController) {
                this.abortController.abort();
                this.isGenerating = false;
            }
        },
        scrollToBottom() {
            this.$nextTick(() => {
                const container = this.$refs.chatContainer;
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        },
        clearChat() {
            if (!confirm('Clear all chat messages?')) return;
            this.messages = [];
        },
        copyMessage(idx) {
            const msg = this.messages[idx];
            if (!msg) return;
            // Get plain text from content (strip HTML)
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = window.marked ? marked.parse(msg.content) : msg.content;
            const text = tempDiv.textContent || tempDiv.innerText;

            navigator.clipboard.writeText(text).then(() => {
                showToast('Message copied', 'success');
                this.messages[idx].copied = true;
                setTimeout(() => {
                    this.messages[idx].copied = false;
                }, 2000);
            });
        }
    }
};

window.ChatComponent = ChatComponent;
