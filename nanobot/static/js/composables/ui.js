/**
 * nanobot UI Utilities Composable
 * Toast notifications, auth, sidebar toggle
 */

// Toast notification system
function showToast(message, type = 'info') {
    const toastEl = document.getElementById('liveToast');
    if (!toastEl) {
        console.log(`[${type.toUpperCase()}] ${message}`);
        return;
    }

    toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
    const toastMessage = document.getElementById('toastMessage');
    if (toastMessage) {
        toastMessage.textContent = message;
    }

    try {
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
    } catch (e) {
        console.error('Failed to show toast:', e);
    }
}

// Authentication utilities
async function checkAuth(apiClient) {
    try {
        const response = await apiClient.get('/api/auth/check');
        if (response.auth_required && !apiClient.getToken()) {
            showAuthPrompt(apiClient);
        } else if (response.auth_required && apiClient.getToken()) {
            const storedToken = apiClient.getToken();
            const verifyResponse = await apiClient.post('/api/auth/verify', { token: storedToken });
            if (!verifyResponse.authenticated) {
                apiClient.setToken(null);
                showAuthPrompt(apiClient);
            }
        }
    } catch (error) {
        console.error('Auth check failed:', error);
    }
}

function showAuthPrompt(apiClient) {
    const token = prompt('Please enter your authentication token:\n\nThis token will be saved in your browser for future visits.');
    if (token) {
        apiClient.setToken(token);
        verifyAuth(token, apiClient);
    }
}

async function verifyAuth(token, apiClient) {
    try {
        const response = await apiClient.post('/api/auth/verify', { token });
        if (response.authenticated) {
            showToast('Authentication successful. Token saved.', 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast('Invalid authentication token', 'danger');
            apiClient.setToken(null);
            setTimeout(() => showAuthPrompt(apiClient), 1500);
        }
    } catch (error) {
        showToast('Authentication failed: ' + error.message, 'danger');
        apiClient.setToken(null);
    }
}

async function updateConnectionStatus(apiClient) {
    const statusEl = document.getElementById('connectionStatus');
    if (!statusEl) return;
    try {
        await apiClient.get('/health');
        statusEl.className = 'badge bg-success me-3';
        statusEl.innerHTML = '<i class="bi bi-circle-fill small"></i> Connected';
    } catch {
        statusEl.className = 'badge bg-danger me-3';
        statusEl.innerHTML = '<i class="bi bi-circle-fill small"></i> Disconnected';
    }
}

// HTML escaping to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Utility exports
window.showToast = showToast;
window.escapeHtml = escapeHtml;
window.checkAuth = checkAuth;
window.showAuthPrompt = showAuthPrompt;
window.verifyAuth = verifyAuth;
window.updateConnectionStatus = updateConnectionStatus;

export { showToast, checkAuth, showAuthPrompt, verifyAuth, updateConnectionStatus, escapeHtml };
