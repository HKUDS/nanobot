/**
 * nanobot Web UI - Main JavaScript
 * Handles API communication, UI interactions, and common utilities
 */

// API Client
const api = {
    baseURL: '',
    token: null,
    
    // Get stored auth token
    getToken() {
        return this.token || localStorage.getItem('nanobot_auth_token');
    },
    
    // Set auth token
    setToken(token) {
        this.token = token;
        if (token) {
            localStorage.setItem('nanobot_auth_token', token);
        } else {
            localStorage.removeItem('nanobot_auth_token');
        }
    },
    
    // Build headers with auth
    getHeaders() {
        const headers = {
            'Content-Type': 'application/json',
        };
        
        const token = this.getToken();
        if (token) {
            headers['X-Auth-Token'] = token;
        }
        
        return headers;
    },
    
    // Generic request handler
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            ...options,
            headers: {
                ...this.getHeaders(),
                ...(options.headers || {}),
            },
        };
        
        try {
            const response = await fetch(url, config);
            
            // Handle authentication errors
            if (response.status === 401) {
                this.setToken(null);
                throw new Error('Authentication required. Please refresh the page.');
            }
            
            // Handle errors
            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: response.statusText }));
                throw new Error(error.error || `HTTP ${response.status}: ${response.statusText}`);
            }
            
            // Parse response
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            }
            
            return await response.text();
        } catch (error) {
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        }
    },
    
    // GET request
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },
    
    // POST request
    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
    
    // PUT request
    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },
    
    // DELETE request
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },
};

// Toast Notifications
function showToast(message, type = 'info') {
    const toastEl = document.getElementById('liveToast');
    
    // If toast element doesn't exist, just log to console
    if (!toastEl) {
        console.log(`[${type.toUpperCase()}] ${message}`);
        return;
    }
    
    const toastMessage = document.getElementById('toastMessage');
    const toastHeader = toastEl.querySelector('.toast-header');

    // Set message
    if (toastMessage) {
        toastMessage.textContent = message;
    }

    // Set color based on type
    if (toastHeader) {
        toastHeader.className = 'toast-header';
    }
    toastEl.className = `toast align-items-center text-white bg-${type} border-0`;

    // Show toast
    try {
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
    } catch (e) {
        console.error('Failed to show toast:', e);
    }
}

// Sidebar Toggle
document.addEventListener('DOMContentLoaded', function() {
    const sidebarToggle = document.getElementById('sidebarToggle');
    const wrapper = document.getElementById('wrapper');
    
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function(e) {
            e.preventDefault();
            wrapper.classList.toggle('sidebar-toggled');
            
            // On mobile, this will slide the sidebar in/out
            // On desktop, you could implement a mini-sidebar if desired
        });
    }
    
    // Check authentication on page load
    checkAuth();
    
    // Update connection status periodically
    updateConnectionStatus();
    setInterval(updateConnectionStatus, 30000); // Check every 30 seconds
});

// Check Authentication
async function checkAuth() {
    try {
        const response = await api.get('/api/auth/check');
        
        // If auth is required and we don't have a token, prompt for it
        if (response.auth_required && !api.getToken()) {
            showAuthPrompt();
        }
        // If auth is required and we have a token, verify it silently
        else if (response.auth_required && api.getToken()) {
            const storedToken = api.getToken();
            const verifyResponse = await api.post('/api/auth/verify', { token: storedToken });
            
            if (!verifyResponse.authenticated) {
                // Token is invalid, clear it and prompt again
                api.setToken(null);
                showAuthPrompt();
            }
        }
        // If auth is not required, we're good
    } catch (error) {
        console.error('Auth check failed:', error);
        // Don't prompt on network errors - might be temporary
    }
}

// Show Authentication Prompt
function showAuthPrompt() {
    const token = prompt('Please enter your authentication token:\n\nThis token will be saved in your browser for future visits.');
    if (token) {
        api.setToken(token);
        verifyAuth(token);
    }
}

// Verify Authentication
async function verifyAuth(token) {
    try {
        const response = await api.post('/api/auth/verify', { token });

        if (response.authenticated) {
            showToast('Authentication successful. Token saved.', 'success');
            updateConnectionStatus();
            // Reload page to refresh all data
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showToast('Invalid authentication token', 'danger');
            api.setToken(null);
            setTimeout(() => showAuthPrompt(), 1500);
        }
    } catch (error) {
        console.error('Auth verification failed:', error);
        showToast('Authentication failed: ' + error.message, 'danger');
        api.setToken(null);
    }
}

// Update Connection Status
async function updateConnectionStatus() {
    const statusEl = document.getElementById('connectionStatus');
    if (!statusEl) return;
    
    try {
        await api.get('/health');
        statusEl.className = 'badge bg-success me-3';
        statusEl.innerHTML = '<i class="bi bi-circle-fill small"></i> Connected';
    } catch (error) {
        statusEl.className = 'badge bg-danger me-3';
        statusEl.innerHTML = '<i class="bi bi-circle-fill small"></i> Disconnected';
    }
}

// Utility Functions

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}

// Format number with commas
function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Local Storage Helpers
const storage = {
    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (error) {
            console.error('Storage get error:', error);
            return defaultValue;
        }
    },
    
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (error) {
            console.error('Storage set error:', error);
        }
    },
    
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (error) {
            console.error('Storage remove error:', error);
        }
    },
    
    clear() {
        try {
            localStorage.clear();
        } catch (error) {
            console.error('Storage clear error:', error);
        }
    },
};

// Event Emitters for Cross-Component Communication
class EventEmitter {
    constructor() {
        this.events = {};
    }
    
    on(event, listener) {
        if (!this.events[event]) {
            this.events[event] = [];
        }
        this.events[event].push(listener);
        return () => this.off(event, listener);
    }
    
    off(event, listener) {
        if (!this.events[event]) return;
        this.events[event] = this.events[event].filter(l => l !== listener);
    }
    
    emit(event, ...args) {
        if (!this.events[event]) return;
        this.events[event].forEach(listener => listener(...args));
    }
}

// Global event emitter
const events = new EventEmitter();

// Export for use in other scripts
window.api = api;
window.showToast = showToast;
window.escapeHtml = escapeHtml;
window.formatDate = formatDate;
window.formatNumber = formatNumber;
window.debounce = debounce;
window.storage = storage;
window.events = events;

// Console welcome message
console.log('%c🐈 nanobot Web UI', 'font-size: 20px; font-weight: bold; color: #0d6efd;');
console.log('%cWelcome to nanobot! Use the dashboard to configure and chat with your AI assistant.', 'font-size: 12px; color: #6c757d;');
