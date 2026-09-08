export interface RuntimeConfigField {
  group: string;
  path: string;
  kind: "duration-toggle" | "toggle" | "text" | "nullable" | "number" | "boolean" | "select" | "list" | "preset";
  options?: string[];
  enabledValue?: number;
  when?: { path: string; value: string | boolean };
  manual?: boolean;
  min?: number;
  max?: number;
}

export type RuntimeConfigPage = "memory" | "runtime" | "automations" | "advanced" | "browser" | "image" | "apps";

export const RUNTIME_CONFIG_GROUPS: { id: string; page: RuntimeConfigPage }[] = [
  { id: "identity", page: "runtime" },
  { id: "memory", page: "memory" },
  { id: "heartbeat", page: "automations" },
  { id: "chat", page: "advanced" },
  { id: "execution", page: "advanced" },
  { id: "sessions", page: "runtime" },
  { id: "maintenance", page: "memory" },
  { id: "tools", page: "runtime" },
  { id: "web", page: "browser" },
  { id: "applications", page: "apps" },
  { id: "shell", page: "advanced" },
  { id: "network", page: "advanced" },
  { id: "safety", page: "advanced" },
  { id: "cli", page: "advanced" },
  { id: "gateway", page: "advanced" },
  { id: "api", page: "advanced" },
  { id: "storage", page: "image" },
];

export const RUNTIME_CONFIG_FIELDS: RuntimeConfigField[] = [
  { group: "identity", path: "agents.defaults.timezone_mode", kind: "toggle", options: ["manual", "auto"] },
  { group: "identity", path: "agents.defaults.timezone", kind: "text", when: { path: "agents.defaults.timezone_mode", value: "manual" } },
  { group: "memory", path: "agents.defaults.session_ttl_minutes", kind: "duration-toggle", enabledValue: 15 },
  { group: "memory", path: "agents.defaults.long_term_memory_enabled", kind: "boolean" },
  { group: "memory", path: "agents.defaults.dream.enabled", kind: "boolean" },
  { group: "memory", path: "agents.defaults.dream.interval_h", kind: "number", min: 1, when: { path: "agents.defaults.dream.enabled", value: true } },
  { group: "memory", path: "agents.defaults.dream.model_override", kind: "preset", when: { path: "agents.defaults.dream.enabled", value: true } },
  { group: "heartbeat", path: "gateway.heartbeat.enabled", kind: "boolean" },
  { group: "heartbeat", path: "gateway.heartbeat.interval_s", kind: "number", min: 1, when: { path: "gateway.heartbeat.enabled", value: true } },
  { group: "execution", path: "agents.defaults.max_tool_iterations", kind: "number", min: 1 },
  { group: "execution", path: "agents.defaults.max_concurrent_subagents", kind: "number", min: 1 },
  { group: "execution", path: "agents.defaults.max_tool_result_chars", kind: "number", min: 1 },
  { group: "execution", path: "agents.defaults.provider_retry_mode", kind: "toggle", options: ["standard", "persistent"] },
  { group: "execution", path: "agents.defaults.tool_hint_max_length", kind: "number", min: 20, max: 500 },
  { group: "execution", path: "tools.max_session_messages_per_minute", kind: "number", min: 1 },
  { group: "sessions", path: "agents.defaults.workspace", kind: "text", manual: true },
  { group: "sessions", path: "agents.defaults.unified_session", kind: "boolean" },
  { group: "maintenance", path: "agents.defaults.idle_compact_check_interval_seconds", kind: "number", min: 0 },
  { group: "maintenance", path: "agents.defaults.dream.cron", kind: "nullable", when: { path: "agents.defaults.dream.enabled", value: true } },
  { group: "tools", path: "tools.exec.enable", kind: "boolean" },
  { group: "tools", path: "tools.file.enable", kind: "boolean" },
  { group: "web", path: "tools.web.enable", kind: "boolean" },
  { group: "applications", path: "tools.cli_apps.enable", kind: "boolean" },
  { group: "tools", path: "tools.my.enable", kind: "boolean" },
  { group: "tools", path: "tools.my.allow_set", kind: "boolean" },
  { group: "shell", path: "tools.exec.timeout", kind: "number", min: 0 },
  { group: "shell", path: "tools.exec.path_prepend", kind: "text" },
  { group: "shell", path: "tools.exec.path_append", kind: "text" },
  { group: "shell", path: "tools.exec.sandbox", kind: "toggle", options: ["", "bwrap"] },
  { group: "shell", path: "tools.exec.sandbox_ro_binds", kind: "list", when: { path: "tools.exec.sandbox", value: "bwrap" } },
  { group: "shell", path: "tools.exec.sandbox_rw_binds", kind: "list", when: { path: "tools.exec.sandbox", value: "bwrap" } },
  { group: "shell", path: "tools.exec.allowed_env_keys", kind: "list" },
  { group: "shell", path: "tools.exec.allow_patterns", kind: "list" },
  { group: "shell", path: "tools.exec.deny_patterns", kind: "list" },
  { group: "network", path: "tools.web.proxy", kind: "nullable" },
  { group: "network", path: "tools.web.user_agent", kind: "nullable" },
  { group: "safety", path: "tools.restrict_to_workspace", kind: "boolean" },
  { group: "safety", path: "tools.ssrf_whitelist", kind: "list" },
  { group: "safety", path: "tools.webui_allow_remote_package_install", kind: "boolean" },
  { group: "cli", path: "tools.cli_apps.install_timeout", kind: "number", min: 1, max: 3600 },
  { group: "cli", path: "tools.cli_apps.run_timeout", kind: "number", min: 1, max: 600 },
  { group: "cli", path: "tools.cli_apps.catalog_ttl_seconds", kind: "number", min: 60, max: 86400 },
  { group: "gateway", path: "gateway.host", kind: "text", manual: true },
  { group: "gateway", path: "gateway.port", kind: "number", min: 1, max: 65535, manual: true },
  { group: "gateway", path: "gateway.restart_mode", kind: "select", options: ["auto", "exec", "spawn", "exit"] },
  { group: "api", path: "api.host", kind: "text", manual: true },
  { group: "api", path: "api.timeout", kind: "number", min: 1, max: 3600 },
  { group: "storage", path: "tools.image_generation.save_dir", kind: "text" },
];
