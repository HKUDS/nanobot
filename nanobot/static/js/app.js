/**
 * nanobot Web UI - Vue 3 SPA Entry Point
 * Initializes Vue app with Vue Router and global components
 */

// Wait for Vue and VueRouter to load
function initApp() {
    const { createApp } = Vue;
    const { createRouter, createWebHashHistory } = VueRouter;

    // Import API client
    const apiClient = window.api;

    // Register components
    const components = {
        'sidebar-component': window.SidebarComponent,
        'dashboard-component': window.DashboardComponent,
        'chat-component': window.ChatComponent,
        'config-component': window.ConfigComponent,
        'status-component': window.StatusComponent,
        'channels-component': window.ChannelsComponent,
    };

    // Define routes
    const routes = [
        { path: '/', component: window.DashboardComponent },
        { path: '/chat', component: window.ChatComponent },
        { path: '/config', component: window.ConfigComponent },
        { path: '/status', component: window.StatusComponent },
        { path: '/channels', component: window.ChannelsComponent },
        // Fallback route
        { path: '/:pathMatch(.*)*', redirect: '/' },
    ];

    // Create router
    const router = createRouter({
        history: createWebHashHistory(),
        routes,
    });

    // Create Vue app
    const app = createApp({
        data() {
            return {
                authenticated: false,
                authRequired: false,
            };
        },
        async mounted() {
            // Check authentication on app load
            await this.checkAuth();
            // Set up periodic connection status checks
            setInterval(() => updateConnectionStatus(apiClient), 30000);
        },
        methods: {
            async checkAuth() {
                try {
                    const response = await apiClient.get('/api/auth/check');
                    this.authRequired = response.auth_required;
                    this.authenticated = response.authenticated;

                    if (response.auth_required && !apiClient.getToken()) {
                        window.showAuthPrompt(apiClient);
                    } else if (response.auth_required && apiClient.getToken()) {
                        const storedToken = apiClient.getToken();
                        const verifyResponse = await apiClient.post('/api/auth/verify', { token: storedToken });
                        if (!verifyResponse.authenticated) {
                            apiClient.setToken(null);
                            window.showAuthPrompt(apiClient);
                        }
                    }
                } catch (error) {
                    console.error('Auth check failed:', error);
                }
            }
        }
    });

    // Register all components
    Object.entries(components).forEach(([name, component]) => {
        if (component) {
            app.component(name, component);
        }
    });

    // Use router
    app.use(router);

    // Mount app
    app.mount('#app');

    // Log welcome message
    console.log('%c🐈 nanobot Web UI', 'font-size: 20px; font-weight: bold; color: #0d6efd;');
    console.log('%cWelcome to nanobot! Vue 3 SPA loaded.', 'font-size: 12px; color: #6c757d;');
}

// Poll for Vue and VueRouter availability
function waitForDeps() {
    if (typeof Vue !== 'undefined' && typeof VueRouter !== 'undefined') {
        initApp();
    } else {
        setTimeout(waitForDeps, 50);
    }
}

// Start waiting
waitForDeps();
