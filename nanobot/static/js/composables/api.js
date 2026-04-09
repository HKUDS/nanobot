/**
 * nanobot API Client Composable
 * Reusable API client for Vue 3 components
 */

const ApiClient = {
    baseURL: '',
    token: null,

    getToken() {
        return this.token || localStorage.getItem('nanobot_auth_token');
    },

    setToken(token) {
        this.token = token;
        if (token) {
            localStorage.setItem('nanobot_auth_token', token);
        } else {
            localStorage.removeItem('nanobot_auth_token');
        }
    },

    getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = this.getToken();
        if (token) {
            headers['X-Auth-Token'] = token;
        }
        return headers;
    },

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            ...options,
            headers: { ...this.getHeaders(), ...(options.headers || {}) },
        };

        const response = await fetch(url, config);

        if (response.status === 401) {
            this.setToken(null);
            throw new Error('Authentication required. Please refresh the page.');
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: response.statusText }));
            throw new Error(error.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        }
        return await response.text();
    },

    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },

    async post(endpoint, data) {
        return this.request(endpoint, { method: 'POST', body: JSON.stringify(data) });
    },

    async put(endpoint, data) {
        return this.request(endpoint, { method: 'PUT', body: JSON.stringify(data) });
    },

    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },

    // SSE streaming helper
    async streamChat(message, sessionId, callbacks) {
        const { onContent, onDone, onError, signal } = callbacks;
        const response = await fetch('/api/chat?stream=true', {
            method: 'POST',
            headers: this.getHeaders(),
            body: JSON.stringify({ message, session_id: sessionId }),
            signal,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') continue;
                    try {
                        const event = JSON.parse(data);
                        if (event.type === 'content') {
                            onContent(event.content);
                        } else if (event.type === 'error') {
                            throw new Error(event.error);
                        } else if (event.type === 'done') {
                            if (event.content && (event.content.startsWith('Error') || event.content.includes('Error calling LLM'))) {
                                throw new Error(event.content);
                            }
                            onDone(event.metadata || {});
                        }
                    } catch (e) {
                        if (e.name !== 'SyntaxError') throw e;
                    }
                }
            }
        }
    },
};

// Make available globally for non-component usage
window.api = ApiClient;

export default ApiClient;
