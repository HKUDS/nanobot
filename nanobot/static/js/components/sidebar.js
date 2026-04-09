/**
 * Sidebar Navigation Component
 */

const SidebarComponent = {
    template: `
        <div class="sidebar" id="sidebar-wrapper" :class="{ collapsed: isCollapsed }">
            <div class="sidebar-heading text-center py-4">
                <img src="/static/img/nanobot_logo.png" alt="nanobot" class="logo-img"
                     @error="handleLogoError">
                <h4 class="mb-0" :style="{ display: logoError ? 'block' : 'none' }">🐈 nanobot</h4>
            </div>
            <div class="list-group list-group-flush">
                <router-link v-for="item in navItems" :key="item.path"
                    :to="item.path"
                    class="list-group-item list-group-item-action"
                    :class="{ active: isActive(item.path) }"
                    @click="handleNavClick">
                    <i :class="'bi ' + item.icon + ' me-2'"></i>{{ item.label }}
                </router-link>
            </div>
        </div>
    `,
    data() {
        return {
            isCollapsed: false,
            logoError: false,
            navItems: [
                { path: '/', icon: 'bi-speedometer2', label: 'Dashboard' },
                { path: '/chat', icon: 'bi-chat-dots', label: 'Chat' },
                { path: '/config', icon: 'bi-gear', label: 'Configuration' },
                { path: '/status', icon: 'bi-activity', label: 'Status' },
                { path: '/channels', icon: 'bi-plug', label: 'Channels' },
            ]
        };
    },
    methods: {
        handleLogoError(e) {
            this.logoError = true;
            e.target.style.display = 'none';
        },
        isActive(path) {
            const currentPath = this.$route.path;
            if (path === '/') return currentPath === '/';
            return currentPath.startsWith(path);
        },
        handleNavClick() {
            // Close sidebar on mobile after navigation
            if (window.innerWidth < 768) {
                document.getElementById('wrapper').classList.remove('sidebar-toggled');
            }
        }
    },
    mounted() {
        const toggle = document.getElementById('sidebarToggle');
        if (toggle) {
            toggle.addEventListener('click', () => {
                document.getElementById('wrapper').classList.toggle('sidebar-toggled');
            });
        }
    }
};

window.SidebarComponent = SidebarComponent;
