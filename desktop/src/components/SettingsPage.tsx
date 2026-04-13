import React, { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import {
  CloseIcon,
  GPTIcon,
  InfoIcon,
  PaletteIcon,
  PlugIcon,
  SaveIcon,
  SettingsIcon,
  SlidersIcon,
  SparklesIcon,
  TrashIcon,
} from "./Icons";

interface SettingsPageProps {
  gatewayUrl: string;
  onGatewayUrlChange: (url: string) => void;
  appearance: AppearanceSettings;
  onAppearanceChange: (next: AppearanceSettings) => void;
}

interface StatusInfo {
  version: string;
  model: string;
  running: boolean;
}

interface ConfigInfo {
  model: string;
  provider: string;
  workspace: string;
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  defaultModelId?: string;
  models?: ModelItem[];
  activeModel?: ModelItem | null;
}

interface ModelItem {
  id: string;
  name: string;
  provider: string;
  model: string;
  apiKey: string | null;
  apiBase: string | null;
  extraHeaders: Record<string, string>;
  maxTokens: number | null;
  contextWindowTokens: number | null;
  temperature: number | null;
  reasoningEffort: string | null;
  enabled: boolean;
}

interface ProviderOption {
  id: string;
  label: string;
  isOAuth?: boolean;
}

interface OAuthStatus {
  authorized: boolean;
  accountId?: string | null;
  error?: string;
}

interface ModelDraft {
  id?: string;
  name: string;
  provider: string;
  model: string;
  apiKey: string;
  apiBase: string;
  extraHeadersText: string;
  maxTokens: string;
  contextWindowTokens: string;
  temperature: string;
  reasoningEffort: string;
  enabled: boolean;
}

export interface AppearanceSettings {
  theme: string;
  bubbleStyle: string;
  fontScale: string;
  motionLevel: string;
  compactMode: boolean;
}

interface ChannelItem {
  id: string;
  name: string;
  enabled: boolean;
  mode: string;
  description: string;
}

interface SkillItem {
  id: string;
  name: string;
  source: string;
  description: string;
  path: string;
  deletable: boolean;
}

interface McpServerItem {
  id: string;
  name: string;
  transport: string;
  enabled: boolean;
  endpoint: string;
}

interface SettingsSectionProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

interface SettingsRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

type SettingsSectionKey =
  | "basic"
  | "models"
  | "appearance"
  | "channels"
  | "skills"
  | "mcp"
  | "about";

const sectionItems: Array<{
  key: SettingsSectionKey;
  label: string;
  description: string;
  icon: React.ReactNode;
}> = [
    { key: "basic", label: "基础配置", description: "连接、模型、工作区", icon: <SettingsIcon /> },
    { key: "models", label: "模型配置", description: "新增、切换与默认模型", icon: <GPTIcon /> },
    { key: "appearance", label: "界面设置", description: "主题、字体、动效", icon: <PaletteIcon /> },
    { key: "channels", label: "通道配置", description: "平台接入与策略", icon: <SlidersIcon /> },
    { key: "skills", label: "Skills 配置", description: "真实目录、新增与删除", icon: <SparklesIcon /> },
    { key: "mcp", label: "MCP 配置", description: "服务器与工具接入", icon: <PlugIcon /> },
    { key: "about", label: "运行信息", description: "版本、状态、路径", icon: <InfoIcon /> },
  ];

const defaultChannels: ChannelItem[] = [
  {
    id: "telegram",
    name: "Telegram",
    enabled: false,
    mode: "mention",
    description: "适合个人消息与通知场景",
  },
  {
    id: "discord",
    name: "Discord",
    enabled: false,
    mode: "mention",
    description: "适合社区或团队协作场景",
  },
  {
    id: "feishu",
    name: "Feishu",
    enabled: false,
    mode: "mention",
    description: "适合企业内网与飞书机器人接入",
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    enabled: false,
    mode: "direct",
    description: "依赖 bridge 登录与二维码绑定",
  },
];

const defaultMcpServers: McpServerItem[] = [
  {
    id: "filesystem",
    name: "Filesystem",
    transport: "stdio",
    enabled: false,
    endpoint: "npx @modelcontextprotocol/server-filesystem",
  },
  {
    id: "browser",
    name: "Browser Automation",
    transport: "streamableHttp",
    enabled: false,
    endpoint: "http://127.0.0.1:3001/mcp",
  },
];

const PROVIDER_DEFAULT_API_BASE: Record<string, string> = {
  deepseek: "https://api.deepseek.com",
};

const PROVIDER_MODEL_OPTIONS: Record<string, string[]> = {
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
};

const PROVIDER_MODEL_PLACEHOLDER: Record<string, string> = {
  openai: "gpt-5",
  openai_codex: "gpt-5",
  gemini: "gemini-2.5-flash",
  gemini_oauth: "gemini-2.5-flash",
};

const readJson = <T,>(key: string, fallback: T): T => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
};

const emptyModelDraft = (): ModelDraft => ({
  name: "",
  provider: "custom",
  model: "",
  apiKey: "",
  apiBase: "",
  extraHeadersText: "{}",
  maxTokens: "",
  contextWindowTokens: "",
  temperature: "",
  reasoningEffort: "",
  enabled: true,
});

const modelDraftFromItem = (item: ModelItem): ModelDraft => ({
  id: item.id,
  name: item.name,
  provider: item.provider === "auto" ? "custom" : item.provider,
  model: item.model,
  apiKey: item.apiKey || "",
  apiBase: item.apiBase || "",
  extraHeadersText: JSON.stringify(item.extraHeaders || {}, null, 2),
  maxTokens: item.maxTokens == null ? "" : String(item.maxTokens),
  contextWindowTokens: item.contextWindowTokens == null ? "" : String(item.contextWindowTokens),
  temperature: item.temperature == null ? "" : String(item.temperature),
  reasoningEffort: item.reasoningEffort || "",
  enabled: item.enabled,
});

const parseHeadersText = (value: string, label: string): Record<string, string> => {
  const parsed = JSON.parse(value || "{}");
  if (parsed && (typeof parsed !== "object" || Array.isArray(parsed))) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return Object.fromEntries(Object.entries(parsed || {}).map(([key, item]) => [String(key), String(item)]));
};

const normalizeFetchError = (error: unknown, fallback: string) => {
  const message = error instanceof Error ? error.message : String(error || "");
  if (/load failed|failed to fetch|networkerror|network error/i.test(message)) {
    return "无法连接到 Gateway，请确认已启动并重启到最新版本。";
  }
  return message || fallback;
};

const SettingsSection: React.FC<SettingsSectionProps> = ({
  title,
  description,
  actions,
  children,
}) => (
  <section className="settings-section-shell">
    {title || description || actions ? (
      <div className={`settings-section-header ${!title ? "titleless" : ""}`}>
        {title || description ? (
          <div className="settings-section-heading">
            {title ? <h2 className="settings-section-title">{title}</h2> : null}
            {description ? <p className="settings-section-desc">{description}</p> : null}
          </div>
        ) : null}
        {actions ? <div className="settings-section-actions">{actions}</div> : null}
      </div>
    ) : null}
    <div className="settings-panel-list">{children}</div>
  </section>
);

const SettingsRow: React.FC<SettingsRowProps> = ({ label, description, children }) => (
  <div className="settings-row">
    <div className="settings-row-main">
      <div className="settings-row-label">{label}</div>
      {description ? <div className="settings-row-desc">{description}</div> : null}
    </div>
    <div className="settings-row-control">{children}</div>
  </div>
);

const SettingsPage: React.FC<SettingsPageProps> = ({
  gatewayUrl,
  onGatewayUrlChange,
  appearance,
  onAppearanceChange,
}) => {
  const [activeSection, setActiveSection] = useState<SettingsSectionKey>("basic");
  const [localUrl, setLocalUrl] = useState(gatewayUrl);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [config, setConfig] = useState<ConfigInfo | null>(null);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [providersOptions, setProvidersOptions] = useState<ProviderOption[]>([]);
  const [defaultModelId, setDefaultModelId] = useState("");
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [modelActionLoading, setModelActionLoading] = useState("");
  const [modelEditorOpen, setModelEditorOpen] = useState(false);
  const [modelEditorError, setModelEditorError] = useState("");
  const [modelTestMessage, setModelTestMessage] = useState("");
  const [modelTestStatus, setModelTestStatus] = useState<"success" | "error" | "">("");
  const [modelDraft, setModelDraft] = useState<ModelDraft>(emptyModelDraft);
  const [oauthStatus, setOauthStatus] = useState<OAuthStatus | null>(null);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [channels, setChannels] = useState<ChannelItem[]>(() =>
    readJson<ChannelItem[]>("nanobot_desktop_channels", defaultChannels)
  );
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState("");

  const [importSkillPath, setImportSkillPath] = useState("");
  const [skillActionLoading, setSkillActionLoading] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<SkillItem | null>(null);
  const [skillContent, setSkillContent] = useState("");
  const [skillContentLoading, setSkillContentLoading] = useState(false);
  const [skillContentDirty, setSkillContentDirty] = useState(false);
  const [mcpServers, setMcpServers] = useState<McpServerItem[]>(() =>
    readJson<McpServerItem[]>("nanobot_desktop_mcp", defaultMcpServers)
  );
  const [mcpEditorOpen, setMcpEditorOpen] = useState(false);
  const [mcpDraft, setMcpDraft] = useState<McpServerItem>({
    id: "",
    name: "",
    transport: "stdio",
    enabled: true,
    endpoint: "",
  });
  const [mcpEditorError, setMcpEditorError] = useState("");

  const openCreateMcp = () => {
    setMcpDraft({
      id: "mcp_" + Date.now().toString(36),
      name: "",
      transport: "stdio",
      enabled: true,
      endpoint: "",
    });
    setMcpEditorError("");
    setMcpEditorOpen(true);
  };

  const openEditMcp = (item: McpServerItem) => {
    setMcpDraft({ ...item });
    setMcpEditorError("");
    setMcpEditorOpen(true);
  };

  const deleteMcp = (item: McpServerItem) => {
    if (!window.confirm(`确定删除 MCP 服务「${item.name}」吗？`)) return;
    setMcpServers((prev) => prev.filter((m) => m.id !== item.id));
    setSaveMessage("MCP 服务已删除");
    window.setTimeout(() => setSaveMessage(""), 1600);
  };

  const saveMcp = () => {
    if (!mcpDraft.name.trim()) return setMcpEditorError("名称不能为空");
    if (!mcpDraft.endpoint.trim()) return setMcpEditorError("配置指令不能为空");

    setMcpServers((prev) => {
      const exists = prev.some((m) => m.id === mcpDraft.id);
      if (exists) {
        return prev.map((m) => (m.id === mcpDraft.id ? mcpDraft : m));
      }
      return [...prev, mcpDraft];
    });
    setMcpEditorOpen(false);
    setSaveMessage("MCP 配置已保存");
    window.setTimeout(() => setSaveMessage(""), 1600);
  };

  const httpUrl = useMemo(
    () => gatewayUrl.replace("ws://", "http://").replace("wss://", "https://"),
    [gatewayUrl]
  );

  useEffect(() => {
    setLocalUrl(gatewayUrl);
  }, [gatewayUrl]);

  useEffect(() => {
    localStorage.setItem("nanobot_desktop_channels", JSON.stringify(channels));
  }, [channels]);

  useEffect(() => {
    localStorage.setItem("nanobot_desktop_mcp", JSON.stringify(mcpServers));
  }, [mcpServers]);

  useEffect(() => {
    const fetchInfo = async () => {
      setLoading(true);
      try {
        const [statusRes, configRes] = await Promise.all([
          fetch(`${httpUrl}/api/status`).catch(() => null),
          fetch(`${httpUrl}/api/config`).catch(() => null),
        ]);
        if (statusRes?.ok) {
          setStatus(await statusRes.json());
        } else {
          setStatus(null);
        }
        if (configRes?.ok) {
          const nextConfig = await configRes.json();
          setConfig(nextConfig);
          setDefaultModelId(nextConfig.defaultModelId || "");
        } else {
          setConfig(null);
        }
      } catch {
        setStatus(null);
        setConfig(null);
      } finally {
        setLoading(false);
      }
    };

    fetchInfo();
  }, [httpUrl]);

  const loadModels = async () => {
    setModelsLoading(true);
    setModelsError("");
    try {
      const response = await fetch(`${httpUrl}/api/models`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "读取模型配置失败");
      }
      setModels(data.items || []);
      setProvidersOptions(data.providers || []);
      setDefaultModelId(data.defaultModelId || "");
    } catch (error) {
      setModels([]);
      setProvidersOptions([]);
      setModelsError(normalizeFetchError(error, "读取模型配置失败"));
    } finally {
      setModelsLoading(false);
    }
  };

  useEffect(() => {
    void loadModels();
  }, [httpUrl]);

  useEffect(() => {
    if (!modelEditorOpen) return;

    const modelOptions = PROVIDER_MODEL_OPTIONS[modelDraft.provider];
    const defaultApiBase = PROVIDER_DEFAULT_API_BASE[modelDraft.provider];

    setModelDraft((prev) => {
      const next: ModelDraft = { ...prev };
      let changed = false;

      if (modelOptions?.length && !modelOptions.includes(prev.model)) {
        next.model = modelOptions[0];
        changed = true;
      }

      if (defaultApiBase && !prev.apiBase.trim()) {
        next.apiBase = defaultApiBase;
        changed = true;
      }

      return changed ? next : prev;
    });
  }, [modelDraft.provider, modelEditorOpen]);

  const enabledChannelCount = channels.filter((item) => item.enabled).length;
  const enabledMcpCount = mcpServers.filter((item) => item.enabled).length;
  const workspacePath = config?.workspace || "";
  const workspaceSkillCount = skills.filter((item) => item.source === "workspace").length;
  const builtinSkillCount = skills.filter((item) => item.source === "builtin").length;
  const workspaceSkills = skills.filter((item) => item.source === "workspace");
  const builtinSkills = skills.filter((item) => item.source === "builtin");

  const loadSkills = async (nextWorkspacePath = workspacePath) => {
    setSkillsLoading(true);
    setSkillsError("");
    try {
      const result = await invoke<SkillItem[]>("list_skills", {
        workspacePath: nextWorkspacePath || null,
      });
      setSkills(result);
    } catch (error) {
      setSkills([]);
      setSkillsError(error instanceof Error ? error.message : "读取 Skills 失败");
    } finally {
      setSkillsLoading(false);
    }
  };

  useEffect(() => {
    const trimmed = localUrl.trim();
    if (!trimmed || trimmed === gatewayUrl) {
      return;
    }

    const timer = window.setTimeout(() => {
      setSaveMessage("基础配置已自动保存");
      onGatewayUrlChange(trimmed);
    }, 700);

    return () => window.clearTimeout(timer);
  }, [localUrl, gatewayUrl, onGatewayUrlChange]);

  useEffect(() => {
    void loadSkills(workspacePath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspacePath]);

  useEffect(() => {
    if (!selectedSkill) {
      setSkillContent("");
      setSkillContentDirty(false);
      return;
    }

    const loadContent = async () => {
      setSkillContentLoading(true);
      setSkillsError("");
      try {
        const content = await invoke<string>("read_skill_content", {
          input: { path: selectedSkill.path },
        });
        setSkillContent(content);
        setSkillContentDirty(false);
      } catch (error) {
        setSkillsError(error instanceof Error ? error.message : "读取 SKILL.md 失败");
      } finally {
        setSkillContentLoading(false);
      }
    };

    void loadContent();
  }, [selectedSkill]);

  const updateAppearance = <K extends keyof AppearanceSettings>(
    key: K,
    value: AppearanceSettings[K]
  ) => {
    onAppearanceChange({ ...appearance, [key]: value });
    setSaveMessage("外观偏好已保存到本地");
    window.setTimeout(() => setSaveMessage(""), 1600);
  };

  const refreshConfigAndModels = async () => {
    const [configRes, modelsRes] = await Promise.all([
      fetch(`${httpUrl}/api/config`).catch(() => null),
      fetch(`${httpUrl}/api/models`).catch(() => null),
    ]);
    if (configRes?.ok) {
      const nextConfig = await configRes.json();
      setConfig(nextConfig);
      setDefaultModelId(nextConfig.defaultModelId || "");
    }
    if (modelsRes?.ok) {
      const nextModels = await modelsRes.json();
      setModels(nextModels.items || []);
      setProvidersOptions(nextModels.providers || []);
      setDefaultModelId(nextModels.defaultModelId || "");
    }
    window.dispatchEvent(new CustomEvent("nanobot-config-changed"));
  };

  const openCreateModel = () => {
    const initialProvider = providersOptions.find((item) => item.id === "deepseek")
      || providersOptions.find((item) => item.id === "zhipu")
      || providersOptions[0]
      || null;
    setModelDraft({
      ...emptyModelDraft(),
      provider: initialProvider?.id || "custom",
    });
    setModelEditorError("");
    setModelTestMessage("");
    setModelTestStatus("");
    setModelEditorOpen(true);
  };

  const selectedProviderOption = useMemo(
    () => providersOptions.find((option) => option.id === modelDraft.provider) || null,
    [providersOptions, modelDraft.provider]
  );
  const isOAuthProvider = Boolean(selectedProviderOption?.isOAuth);
  const oauthLoginCommand = modelDraft.provider === "gemini_oauth"
    ? "gcloud auth application-default login"
    : "nanobot provider login openai-codex";

  useEffect(() => {
    if (!modelEditorOpen || !isOAuthProvider) {
      setOauthStatus(null);
      setOauthLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      setOauthLoading(true);
      try {
        const providerId = modelDraft.provider.replace(/_/g, "-");
        const response = await fetch(`${httpUrl}/api/oauth/${providerId}/status`);
        const data = await response.json().catch(() => ({}));
        if (!cancelled) {
          setOauthStatus({
            authorized: Boolean(data.authorized),
            accountId: typeof data.accountId === "string" ? data.accountId : null,
            error: typeof data.error === "string" ? data.error : undefined,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setOauthStatus({
            authorized: false,
            error: error instanceof Error ? error.message : "检查授权状态失败",
          });
        }
      } finally {
        if (!cancelled) {
          setOauthLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [httpUrl, isOAuthProvider, modelDraft.provider, modelEditorOpen]);

  const openEditModel = (item: ModelItem) => {
    setModelDraft(modelDraftFromItem(item));
    setModelEditorError("");
    setModelTestMessage("");
    setModelTestStatus("");
    setModelEditorOpen(true);
  };

  const submitModelDraft = async () => {
    setModelEditorError("");
    setModelActionLoading(modelDraft.id || "create");
    try {
      const parsedHeaders = parseHeadersText(modelDraft.extraHeadersText, "模型 Extra Headers");
      const payload = {
        name: modelDraft.name.trim(),
        provider: modelDraft.provider,
        model: modelDraft.model.trim(),
        apiKey: modelDraft.apiKey.trim() || null,
        apiBase: modelDraft.apiBase.trim() || null,
        extraHeaders: parsedHeaders,
        maxTokens: modelDraft.maxTokens ? Number(modelDraft.maxTokens) : null,
        contextWindowTokens: modelDraft.contextWindowTokens ? Number(modelDraft.contextWindowTokens) : null,
        temperature: modelDraft.temperature ? Number(modelDraft.temperature) : null,
        reasoningEffort: modelDraft.reasoningEffort || null,
        enabled: modelDraft.enabled,
      };
      if (!payload.name) throw new Error("显示名称不能为空");
      if (!payload.model) throw new Error("模型名不能为空");
      if (payload.maxTokens !== null && (!Number.isInteger(payload.maxTokens) || payload.maxTokens <= 0)) {
        throw new Error("Max Tokens 必须是正整数");
      }
      if (
        payload.contextWindowTokens !== null &&
        (!Number.isInteger(payload.contextWindowTokens) || payload.contextWindowTokens <= 0)
      ) {
        throw new Error("Context Window 必须是正整数");
      }
      if (payload.temperature !== null && Number.isNaN(payload.temperature)) {
        throw new Error("Temperature 必须是数字");
      }

      const response = await fetch(
        modelDraft.id ? `${httpUrl}/api/models/${modelDraft.id}` : `${httpUrl}/api/models`,
        {
          method: modelDraft.id ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "保存模型失败");
      }
      setSaveMessage(modelDraft.id ? "模型已更新" : "模型已添加");
      setModelEditorOpen(false);
      await refreshConfigAndModels();
    } catch (error) {
      setModelEditorError(error instanceof Error ? error.message : "保存模型失败");
    } finally {
      setModelActionLoading("");
    }
  };

  const testModelDraft = async () => {
    setModelEditorError("");
    setModelTestMessage("");
    setModelTestStatus("");
    setModelActionLoading(`test:${modelDraft.id || "create"}`);
    try {
      const parsedHeaders = parseHeadersText(modelDraft.extraHeadersText, "模型 Extra Headers");
      const payload = {
        id: modelDraft.id,
        name: modelDraft.name.trim() || "临时测试模型",
        provider: modelDraft.provider,
        model: modelDraft.model.trim(),
        apiKey: modelDraft.apiKey.trim() || null,
        apiBase: modelDraft.apiBase.trim() || null,
        extraHeaders: parsedHeaders,
        maxTokens: modelDraft.maxTokens ? Number(modelDraft.maxTokens) : null,
        contextWindowTokens: modelDraft.contextWindowTokens ? Number(modelDraft.contextWindowTokens) : null,
        temperature: modelDraft.temperature ? Number(modelDraft.temperature) : null,
        reasoningEffort: modelDraft.reasoningEffort || null,
        enabled: modelDraft.enabled,
        // Keep old gateways working until they pick up model-level apiKey support.
        providerConfig: modelDraft.provider === "auto" || isOAuthProvider
          ? null
          : {
            apiKey: modelDraft.apiKey.trim(),
            apiBase: modelDraft.apiBase.trim() || null,
            extraHeaders: parsedHeaders,
          },
      };
      if (!payload.model) throw new Error("模型名不能为空");

      const response = await fetch(`${httpUrl}/api/models/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "测试连通性失败");
      }
      setModelTestStatus("success");
      setModelTestMessage(`连接成功 · ${data.provider} / ${data.model} · 返回: ${data.message}`);
    } catch (error) {
      setModelTestStatus("error");
      setModelTestMessage(error instanceof Error ? error.message : "测试连通性失败");
    } finally {
      setModelActionLoading("");
    }
  };

  const refreshOauthStatus = async () => {
    if (!isOAuthProvider) return;
    setOauthLoading(true);
    try {
      const providerId = modelDraft.provider.replace(/_/g, "-");
      const response = await fetch(`${httpUrl}/api/oauth/${providerId}/status`);
      const data = await response.json().catch(() => ({}));
      setOauthStatus({
        authorized: Boolean(data.authorized),
        accountId: typeof data.accountId === "string" ? data.accountId : null,
        error: typeof data.error === "string" ? data.error : undefined,
      });
    } catch (error) {
      setOauthStatus({
        authorized: false,
        error: error instanceof Error ? error.message : "检查授权状态失败",
      });
    } finally {
      setOauthLoading(false);
    }
  };

  const revokeOauth = async () => {
    if (!isOAuthProvider) return;
    setOauthLoading(true);
    try {
      const providerId = modelDraft.provider.replace(/_/g, "-");
      const response = await fetch(`${httpUrl}/api/oauth/${providerId}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "去授权失败");
      }
      setOauthStatus({ authorized: false });
      setSaveMessage("OAuth 授权已清除");
    } catch (error) {
      setOauthStatus({
        authorized: false,
        error: error instanceof Error ? error.message : "去授权失败",
      });
    } finally {
      setOauthLoading(false);
    }
  };

  const importOauthConfig = async () => {
    if (!isOAuthProvider) return;
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (!selectedPath) return;
    setOauthLoading(true);
    try {
      const providerId = modelDraft.provider.replace(/_/g, "-");
      const response = await fetch(`${httpUrl}/api/oauth/${providerId}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: selectedPath }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "导入本地配置失败");
      }
      setOauthStatus({
        authorized: Boolean(data.authorized),
        accountId: typeof data.accountId === "string" ? data.accountId : null,
      });
      setSaveMessage("本地 OAuth 配置已导入");
    } catch (error) {
      setOauthStatus({
        authorized: false,
        error: error instanceof Error ? error.message : "导入本地配置失败",
      });
    } finally {
      setOauthLoading(false);
    }
  };

  const selectDefaultModel = async (item: ModelItem) => {
    setModelsError("");
    setModelActionLoading(`select:${item.id}`);
    try {
      const response = await fetch(`${httpUrl}/api/models/${item.id}/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "设置默认模型失败");
      }
      setSaveMessage("默认模型已更新");
      await refreshConfigAndModels();
    } catch (error) {
      setModelsError(error instanceof Error ? error.message : "设置默认模型失败");
    } finally {
      setModelActionLoading("");
    }
  };

  const deleteModel = async (item: ModelItem) => {
    if (!window.confirm(`确定删除模型「${item.name}」吗？`)) return;
    setModelsError("");
    setModelActionLoading(`delete:${item.id}`);
    try {
      const response = await fetch(`${httpUrl}/api/models/${item.id}`, {
        method: "DELETE",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "删除模型失败");
      }
      setSaveMessage("模型已删除");
      await refreshConfigAndModels();
    } catch (error) {
      setModelsError(error instanceof Error ? error.message : "删除模型失败");
    } finally {
      setModelActionLoading("");
    }
  };

  const renderBasicSection = () => (
    <div className="settings-content-stack">
      <SettingsSection
        title="连接"
        description="桌面端连接的 Gateway 地址，修改后自动保存。"
      >
        <SettingsRow label="Gateway WebSocket 地址" description="保存后会自动重连。">
          <div className="settings-control-block settings-control-wide">
            <input
              type="text"
              className="settings-input"
              value={localUrl}
              onChange={(event) => setLocalUrl(event.target.value)}
              placeholder="ws://localhost:18790"
            />
          </div>
        </SettingsRow>

        <SettingsRow label="HTTP API 基地址">
          <div className="settings-control-block">
            <input type="text" className="settings-input" value={httpUrl} readOnly />
          </div>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="运行配置" description="来自当前连接的 Gateway。">
        {loading ? (
          <div className="settings-empty-card">正在加载运行配置...</div>
        ) : config ? (
          <>
            <SettingsRow label="运行状态" description={status?.version ? `版本 ${status.version}` : "版本未知"}>
              <span className={`settings-status-pill ${status?.running ? "running" : "stopped"}`}>
                {status?.running ? "运行中" : "未连接"}
              </span>
            </SettingsRow>
            <SettingsRow label="模型">
              <div className="settings-static-value">{config.model}</div>
            </SettingsRow>
            <SettingsRow label="Provider">
              <div className="settings-static-value">{config.provider}</div>
            </SettingsRow>
            <SettingsRow label="Max Tokens">
              <div className="settings-static-value">{config.maxTokens.toLocaleString()}</div>
            </SettingsRow>
            <SettingsRow label="Context Window">
              <div className="settings-static-value">{config.contextWindowTokens.toLocaleString()}</div>
            </SettingsRow>
            <SettingsRow label="Workspace">
              <div className="settings-static-value settings-mono-text">{config.workspace}</div>
            </SettingsRow>
          </>
        ) : (
          <div className="settings-empty-card">当前无法从 gateway 读取运行配置。</div>
        )}
      </SettingsSection>
    </div>
  );

  const renderAppearanceSection = () => (
    <div className="settings-content-stack">
      <SettingsSection title="界面设置" description="当前仅保存在本地。">
        <SettingsRow label="主题模式">
          <div className="settings-control-block settings-select-wrap">
            <select
              className="settings-select"
              value={appearance.theme}
              onChange={(event) => updateAppearance("theme", event.target.value)}
            >
              <option value="system">跟随系统</option>
              <option value="dark">深色</option>
              <option value="light">浅色</option>
            </select>
          </div>
        </SettingsRow>
        <SettingsRow label="消息气泡风格">
          <div className="settings-control-block settings-select-wrap">
            <select
              className="settings-select"
              value={appearance.bubbleStyle}
              onChange={(event) => updateAppearance("bubbleStyle", event.target.value)}
            >
              <option value="rounded">圆角柔和</option>
              <option value="sharp">更利落</option>
              <option value="card">卡片感</option>
            </select>
          </div>
        </SettingsRow>
        <SettingsRow label="字体大小">
          <div className="settings-control-block settings-select-wrap">
            <select
              className="settings-select"
              value={appearance.fontScale}
              onChange={(event) => updateAppearance("fontScale", event.target.value)}
            >
              <option value="small">偏小</option>
              <option value="medium">标准</option>
              <option value="large">偏大</option>
            </select>
          </div>
        </SettingsRow>
        <SettingsRow label="动效强度">
          <div className="settings-control-block settings-select-wrap">
            <select
              className="settings-select"
              value={appearance.motionLevel}
              onChange={(event) => updateAppearance("motionLevel", event.target.value)}
            >
              <option value="minimal">最少</option>
              <option value="balanced">平衡</option>
              <option value="rich">更丰富</option>
            </select>
          </div>
        </SettingsRow>
        <SettingsRow label="紧凑模式" description="减少留白，让表单更密集。">
          <label className="settings-switch">
            <input
              type="checkbox"
              checked={appearance.compactMode}
              onChange={(event) => updateAppearance("compactMode", event.target.checked)}
            />
            <span />
          </label>
        </SettingsRow>
      </SettingsSection>
    </div>
  );

  const renderModelsSection = () => (
    <div className="settings-content-stack">
      <SettingsSection
        title="模型配置"
        description="管理模型列表，并从中选择当前默认模型。"
        actions={
          <button type="button" className="settings-action-btn" onClick={openCreateModel}>
            添加模型
          </button>
        }
      >
        {modelsError ? <div className="settings-empty-card">{modelsError}</div> : null}
        {modelsLoading ? (
          <div className="settings-empty-card">正在读取模型配置...</div>
        ) : models.length === 0 ? (
          <div className="settings-empty-card">当前还没有模型配置，请先添加一个模型。</div>
        ) : (
          <div className="settings-list settings-list-plain">
            {models.map((item) => {
              const isDefault = defaultModelId === item.id;
              const providerLabel =
                item.provider === "auto"
                  ? "Custom"
                  : providersOptions.find((option) => option.id === item.provider)?.label || item.provider;
              return (
                <div className="settings-list-item" key={item.id}>
                  <div className="settings-list-main">
                    <div className="settings-list-head">
                      <strong>{item.name}</strong>
                      {isDefault ? <span className="settings-mini-pill enabled">默认</span> : null}
                      <span className="settings-mini-pill neutral">{providerLabel}</span>
                      <span className={`settings-mini-pill ${item.enabled ? "enabled" : "disabled"}`}>
                        {item.enabled ? "启用" : "停用"}
                      </span>
                    </div>
                    <p className="settings-mono-text">{item.model}</p>
                    <p className="settings-inline-hint">
                      API Key: {item.apiKey ? "单独配置" : "沿用 Provider"} ·
                      API Base: {item.apiBase || "沿用 Provider 默认配置"} ·
                      Max Tokens: {item.maxTokens ?? "默认"} ·
                      Context: {item.contextWindowTokens ?? "默认"} ·
                      Temperature: {item.temperature ?? "默认"}
                    </p>
                  </div>
                  <div className="settings-list-actions">
                    {!isDefault ? (
                      <button
                        type="button"
                        className="settings-action-btn"
                        disabled={!item.enabled || modelActionLoading !== ""}
                        onClick={() => void selectDefaultModel(item)}
                      >
                        设为默认
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="settings-action-btn"
                      disabled={modelActionLoading !== ""}
                      onClick={() => openEditModel(item)}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      className="settings-action-btn danger"
                      disabled={modelActionLoading !== ""}
                      onClick={() => void deleteModel(item)}
                    >
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </SettingsSection>
    </div>
  );

  const renderChannelsSection = () => (
    <div className="settings-content-stack">
      <SettingsSection
        title="通道配置"
        description="预留多平台接入管理。"
        actions={<div className="settings-summary-badge">已启用 {enabledChannelCount} / {channels.length}</div>}
      >
        <div className="settings-list settings-list-plain">
          {channels.map((item) => (
            <div className="settings-list-item" key={item.id}>
              <div className="settings-list-main">
                <div className="settings-list-head">
                  <strong>{item.name}</strong>
                  <span className={`settings-mini-pill ${item.enabled ? "enabled" : "disabled"}`}>
                    {item.enabled ? "启用中" : "未启用"}
                  </span>
                </div>
                <p>{item.description}</p>
              </div>
              <div className="settings-list-actions">
                <div className="settings-select-wrap settings-select-wrap-compact">
                  <select
                    className="settings-select settings-select-compact"
                    value={item.mode}
                    onChange={(event) =>
                      setChannels((prev) =>
                        prev.map((channel) =>
                          channel.id === item.id ? { ...channel, mode: event.target.value } : channel
                        )
                      )
                    }
                  >
                    <option value="mention">mention</option>
                    <option value="open">open</option>
                    <option value="direct">direct</option>
                  </select>
                </div>
                <label className="settings-switch">
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    onChange={(event) =>
                      setChannels((prev) =>
                        prev.map((channel) =>
                          channel.id === item.id ? { ...channel, enabled: event.target.checked } : channel
                        )
                      )
                    }
                  />
                  <span />
                </label>
              </div>
            </div>
          ))}
        </div>
      </SettingsSection>
    </div>
  );

  const renderSkillsSection = () => (
    <div className="settings-content-stack">
      <SettingsSection
        title="Skills 配置"
        description="直接读取 builtin 与 workspace/skills 目录。"
        actions={
          <div className="settings-summary-badge">
            内置 {builtinSkillCount} / 自定义 {workspaceSkillCount}
          </div>
        }
      >
        <SettingsRow label="当前 Skills 目录" description="新增与删除都作用于当前 workspace。">
          <div className="settings-static-value settings-mono-text">
            {workspacePath ? `${workspacePath}/skills` : "等待 gateway 返回 workspace 路径"}
          </div>
        </SettingsRow>

        <SettingsRow label="导入 Skill" description="支持本地 skill 目录，或标准 .skill 包。">
          <div className="settings-control-block settings-control-wide">
            <div className="settings-inline-form">
              <input
                type="text"
                className="settings-input"
                value={importSkillPath}
                onChange={(event) => setImportSkillPath(event.target.value)}
                placeholder="/absolute/path/to/skill-folder 或 /path/to/demo.skill"
                disabled={!workspacePath || skillActionLoading}
              />
              <button
                type="button"
                className="settings-action-btn"
                disabled={!workspacePath || skillActionLoading}
                onClick={async () => {
                  const selected = await open({
                    directory: false,
                    multiple: false,
                    filters: [{ name: "Skill Package", extensions: ["skill"] }],
                  });

                  if (typeof selected === "string") {
                    setImportSkillPath(selected);
                    return;
                  }

                  const selectedDir = await open({
                    directory: true,
                    multiple: false,
                    title: "选择 Skill 文件夹",
                  });

                  if (typeof selectedDir === "string") {
                    setImportSkillPath(selectedDir);
                  }
                }}
              >
                选择
              </button>
              <button
                type="button"
                className="settings-action-btn"
                disabled={!workspacePath || !importSkillPath.trim() || skillActionLoading}
                onClick={async () => {
                  if (!workspacePath || !importSkillPath.trim()) return;
                  setSkillActionLoading(true);
                  setSkillsError("");
                  try {
                    await invoke("import_skill", {
                      input: {
                        workspacePath,
                        sourcePath: importSkillPath,
                      },
                    });
                    setImportSkillPath("");
                    setSaveMessage("Skill 已导入");
                    void loadSkills(workspacePath);
                  } catch (error) {
                    setSkillsError(error instanceof Error ? error.message : "导入 Skill 失败");
                  } finally {
                    setSkillActionLoading(false);
                  }
                }}
              >
                导入
              </button>
            </div>
          </div>
        </SettingsRow>
        {skillsError ? <div className="settings-empty-card">{skillsError}</div> : null}
        {skillsLoading ? <div className="settings-empty-card">正在读取 Skills...</div> : null}
      </SettingsSection>

      {!skillsLoading && skills.length === 0 ? (
        <div className="settings-empty-card">当前未发现任何 Skill。</div>
      ) : null}

      {workspaceSkills.length > 0 ? (
        <SettingsSection
          title="Workspace Skills"
          description="当前工作区下可编辑、可删除的自定义 Skills。"
          actions={<div className="settings-summary-badge">{workspaceSkills.length}</div>}
        >
          <div className="settings-list settings-list-plain">
            {workspaceSkills.map((item) => (
              <div className="settings-list-item" key={item.id}>
                <div className="settings-list-main">
                  <div className="settings-list-head">
                    <strong>{item.name}</strong>
                    <span className="settings-mini-pill neutral">{item.source}</span>
                  </div>
                  <p>{item.description}</p>
                  <p className="settings-inline-hint settings-mono-text">{item.path}</p>
                </div>
                <div className="settings-list-actions">
                  <button
                    type="button"
                    className="settings-action-btn"
                    disabled={skillActionLoading}
                    onClick={() => setSelectedSkill(item)}
                  >
                    编辑
                  </button>
                </div>
              </div>
            ))}
          </div>
        </SettingsSection>
      ) : null}

      {builtinSkills.length > 0 ? (
        <SettingsSection
          title="Builtin Skills"
          description="项目内置 Skills，只读可查看。"
          actions={<div className="settings-summary-badge">{builtinSkills.length}</div>}
        >
          <div className="settings-list settings-list-plain">
            {builtinSkills.map((item) => (
              <div className="settings-list-item" key={item.id}>
                <div className="settings-list-main">
                  <div className="settings-list-head">
                    <strong>{item.name}</strong>
                    <span className="settings-mini-pill neutral">{item.source}</span>
                  </div>
                  <p>{item.description}</p>
                  <p className="settings-inline-hint settings-mono-text">{item.path}</p>
                </div>
                <div className="settings-list-actions">
                  <button
                    type="button"
                    className="settings-action-btn"
                    disabled={skillActionLoading}
                    onClick={() => setSelectedSkill(item)}
                  >
                    查看
                  </button>
                </div>
              </div>
            ))}
          </div>
        </SettingsSection>
      ) : null}

    </div>
  );

  const renderMcpSection = () => (
    <div className="settings-content-stack">
      <SettingsSection
        title="MCP 配置"
        description="本地 MCP 服务器清单与启用状态。"
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div className="settings-summary-badge">已启用 {enabledMcpCount} / {mcpServers.length}</div>
            <button type="button" className="settings-action-btn" onClick={openCreateMcp}>添加服务</button>
          </div>
        }
      >
        {mcpServers.length === 0 ? (
          <div className="settings-empty-card">当前没有配置任何 MCP 服务。</div>
        ) : (
          <div className="settings-list settings-list-plain">
            {mcpServers.map((item) => (
              <div className="settings-list-item" key={item.id}>
                <div className="settings-list-main">
                  <div className="settings-list-head">
                    <strong>{item.name}</strong>
                    <span className="settings-mini-pill neutral">{item.transport}</span>
                  </div>
                  <p className="settings-mono-text">{item.endpoint}</p>
                </div>
                <div className="settings-list-actions">
                  <button type="button" className="settings-action-btn" onClick={() => openEditMcp(item)}>编辑</button>
                  <button type="button" className="settings-action-btn danger" onClick={() => deleteMcp(item)}>删除</button>
                  <label className="settings-switch" style={{ marginLeft: "8px" }}>
                    <input
                      type="checkbox"
                      checked={item.enabled}
                      onChange={(event) =>
                        setMcpServers((prev) =>
                          prev.map((server) =>
                            server.id === item.id ? { ...server, enabled: event.target.checked } : server
                          )
                        )
                      }
                    />
                    <span />
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}
      </SettingsSection>
    </div>
  );

  const renderAboutSection = () => (
    <div className="settings-content-stack">
      <SettingsSection title="运行信息" description="桌面端与后端状态汇总。">
        <SettingsRow label="Gateway 状态">
          <div className="settings-static-value">{status?.running ? "运行中" : "未连接"}</div>
        </SettingsRow>
        <SettingsRow label="后端版本">
          <div className="settings-static-value">{status?.version || "未知"}</div>
        </SettingsRow>
        <SettingsRow label="Gateway 地址">
          <div className="settings-static-value settings-mono-text">{gatewayUrl}</div>
        </SettingsRow>
        <SettingsRow label="工作区路径">
          <div className="settings-static-value settings-mono-text">{config?.workspace || "未获取到"}</div>
        </SettingsRow>
      </SettingsSection>
    </div>
  );

  const renderSectionContent = () => {
    switch (activeSection) {
      case "basic":
        return renderBasicSection();
      case "appearance":
        return renderAppearanceSection();
      case "models":
        return renderModelsSection();
      case "channels":
        return renderChannelsSection();
      case "skills":
        return renderSkillsSection();
      case "mcp":
        return renderMcpSection();
      case "about":
        return renderAboutSection();
      default:
        return null;
    }
  };

  return (
    <div className="settings-page">
      <div className="settings-shell-body">
        <aside className="settings-nav">
          <div className="settings-nav-header">
            <h1 className="settings-nav-title">设置</h1>
          </div>
          <div className="settings-nav-group">
            {sectionItems.map((item) => (
              <button
                key={item.key}
                className={`settings-nav-item ${activeSection === item.key ? "active" : ""}`}
                onClick={() => setActiveSection(item.key)}
              >
                <span className="settings-nav-icon">{item.icon}</span>
                <span className="settings-nav-label">{item.label}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="settings-main">
          <header className="settings-shell-header">
            <div className="settings-shell-actions">
              {saveMessage ? <span className="settings-save-feedback">{saveMessage}</span> : null}
            </div>
          </header>
          {renderSectionContent()}
        </main>
      </div>
      {selectedSkill ? (
        <div className="settings-dialog-backdrop" onClick={() => setSelectedSkill(null)}>
          <div className="settings-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="settings-dialog-header">
              <div className="settings-dialog-heading">
                <p className="settings-shell-kicker">{selectedSkill.deletable ? "编辑 Skill" : "查看 Skill"}</p>
                <h2 className="settings-dialog-title">{selectedSkill.name}</h2>
                <p className="settings-dialog-path settings-mono-text">{selectedSkill.path}</p>
              </div>
              <div className="settings-list-actions">
                {selectedSkill.deletable ? (
                  <>
                    <button
                      type="button"
                      className="settings-icon-btn"
                      disabled={skillContentLoading || !skillContentDirty || skillActionLoading}
                      onClick={async () => {
                        setSkillActionLoading(true);
                        setSkillsError("");
                        try {
                          await invoke("update_skill_content", {
                            input: { path: selectedSkill.path, content: skillContent },
                          });
                          setSkillContentDirty(false);
                          setSaveMessage("SKILL.md 已保存");
                          void loadSkills(workspacePath);
                        } catch (error) {
                          setSkillsError(error instanceof Error ? error.message : "保存 SKILL.md 失败");
                        } finally {
                          setSkillActionLoading(false);
                        }
                      }}
                      aria-label="保存"
                      title="保存"
                    >
                      <SaveIcon />
                    </button>
                    <button
                      type="button"
                      className="settings-icon-btn danger"
                      disabled={skillActionLoading}
                      onClick={async () => {
                        if (!workspacePath) return;
                        setSkillActionLoading(true);
                        setSkillsError("");
                        try {
                          await invoke("delete_skill", {
                            workspacePath,
                            name: selectedSkill.name,
                          });
                          setSaveMessage("Skill 已删除");
                          setSelectedSkill(null);
                          void loadSkills(workspacePath);
                        } catch (error) {
                          setSkillsError(error instanceof Error ? error.message : "删除 Skill 失败");
                        } finally {
                          setSkillActionLoading(false);
                        }
                      }}
                      aria-label="删除"
                      title="删除"
                    >
                      <TrashIcon />
                    </button>
                  </>
                ) : (
                  <span className="settings-mini-pill neutral">builtin 只读</span>
                )}
                <button
                  type="button"
                  className="settings-icon-btn"
                  disabled={skillActionLoading}
                  onClick={() => setSelectedSkill(null)}
                  aria-label="关闭"
                  title="关闭"
                >
                  <CloseIcon />
                </button>
              </div>
            </div>
            <div className="settings-dialog-body">
              {skillContentLoading ? (
                <div className="settings-empty-card">正在读取 SKILL.md...</div>
              ) : (
                <textarea
                  className="settings-textarea"
                  value={skillContent}
                  onChange={(event) => {
                    setSkillContent(event.target.value);
                    setSkillContentDirty(true);
                  }}
                  readOnly={!selectedSkill.deletable}
                  spellCheck={false}
                />
              )}
            </div>
          </div>
        </div>
      ) : null}
      {modelEditorOpen ? (
        <div className="settings-dialog-backdrop" onClick={() => setModelEditorOpen(false)}>
          <div className="settings-dialog settings-model-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="settings-dialog-header">
              <div className="settings-dialog-heading">
                <p className="settings-shell-kicker">{modelDraft.id ? "编辑模型" : "新增模型"}</p>
                <h2 className="settings-dialog-title">{modelDraft.id ? modelDraft.name || "编辑模型" : "新增模型"}</h2>
              </div>
              <div className="settings-list-actions">
                <button
                  type="button"
                  className="settings-action-btn"
                  disabled={modelActionLoading !== ""}
                  onClick={testModelDraft}
                >
                  测试连接
                </button>
                <button
                  type="button"
                  className="settings-icon-btn"
                  disabled={modelActionLoading !== ""}
                  onClick={submitModelDraft}
                  aria-label="保存"
                  title="保存"
                >
                  <SaveIcon />
                </button>
                <button
                  type="button"
                  className="settings-icon-btn"
                  disabled={modelActionLoading !== ""}
                  onClick={() => setModelEditorOpen(false)}
                  aria-label="关闭"
                  title="关闭"
                >
                  <CloseIcon />
                </button>
              </div>
            </div>
            <div className="settings-dialog-body settings-model-body">
              {modelEditorError ? <div className="settings-empty-card">{modelEditorError}</div> : null}
              {modelTestMessage ? (
                <div className={`settings-empty-card ${modelTestStatus === "success" ? "settings-test-card success" : "settings-test-card error"}`}>
                  {modelTestMessage}
                </div>
              ) : null}
              <div className="settings-model-grid">
                <label className="settings-model-field">
                  <span>显示名称</span>
                  <input
                    type="text"
                    className="settings-input"
                    value={modelDraft.name}
                    onChange={(event) => setModelDraft((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="例如：Claude 4.5 主力"
                  />
                </label>
                <label className="settings-model-field">
                  <span>Provider</span>
                  <div className="settings-select-wrap">
                    <select
                      className="settings-select"
                      value={modelDraft.provider}
                      onChange={(event) => setModelDraft((prev) => ({ ...prev, provider: event.target.value }))}
                    >
                      {providersOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
                <label className="settings-model-field settings-model-field-full">
                  <span>模型名</span>
                  {modelDraft.provider === "deepseek" ? (
                    <div className="settings-select-wrap">
                      <select
                        className="settings-select"
                        value={modelDraft.model}
                        onChange={(event) => setModelDraft((prev) => ({ ...prev, model: event.target.value }))}
                      >
                        {PROVIDER_MODEL_OPTIONS.deepseek.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <input
                      type="text"
                      className="settings-input settings-mono-input"
                      value={modelDraft.model}
                      onChange={(event) => setModelDraft((prev) => ({ ...prev, model: event.target.value }))}
                      placeholder={PROVIDER_MODEL_PLACEHOLDER[modelDraft.provider] || "anthropic/claude-opus-4-5"}
                    />
                  )}
                </label>
                {isOAuthProvider ? (
                  <div className="settings-model-field settings-model-field-full">
                    <span>认证方式</span>
                    <div className="settings-empty-card">
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        <div>
                          当前 Provider 使用 OAuth 认证，不需要填写 API Key。请先在命令行执行
                          <span className="settings-mono-text"> {oauthLoginCommand} </span>
                          完成授权。
                        </div>
                        <div>
                          当前状态：
                          {oauthLoading ? " 正在检查..." : oauthStatus?.authorized ? " 已授权" : " 未授权"}
                          {oauthStatus?.accountId ? ` · ${oauthStatus.accountId}` : ""}
                        </div>
                        {oauthStatus?.error ? <div>{oauthStatus.error}</div> : null}
                        <div className="settings-section-actions">
                          {modelDraft.provider === "gemini_oauth" ? (
                            <button
                              type="button"
                              className="settings-secondary-btn"
                              onClick={importOauthConfig}
                              disabled={oauthLoading}
                            >
                              导入本地配置
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="settings-secondary-btn"
                            onClick={refreshOauthStatus}
                            disabled={oauthLoading}
                          >
                            检查是否已授权
                          </button>
                          <button
                            type="button"
                            className="settings-secondary-btn danger"
                            onClick={revokeOauth}
                            disabled={oauthLoading || !oauthStatus?.authorized}
                          >
                            去授权
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <label className="settings-model-field settings-model-field-full">
                      <span>API Base</span>
                      <input
                        type="text"
                        className="settings-input settings-mono-input"
                        value={modelDraft.apiBase}
                        onChange={(event) => setModelDraft((prev) => ({ ...prev, apiBase: event.target.value }))}
                        placeholder="留空则沿用 Provider 默认配置"
                      />
                    </label>
                    <label className="settings-model-field settings-model-field-full">
                      <span>API Key</span>
                      <input
                        type="password"
                        className="settings-input settings-mono-input"
                        value={modelDraft.apiKey}
                        onChange={(event) => setModelDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                        placeholder="留空则沿用 Provider 默认配置"
                      />
                    </label>
                    <label className="settings-model-field settings-model-field-full">
                      <span>Extra Headers (JSON)</span>
                      <textarea
                        className="settings-input settings-model-headers settings-mono-input"
                        value={modelDraft.extraHeadersText}
                        onChange={(event) => setModelDraft((prev) => ({ ...prev, extraHeadersText: event.target.value }))}
                        spellCheck={false}
                      />
                    </label>
                  </>
                )}
                <label className="settings-model-field">
                  <span>Max Tokens</span>
                  <input
                    type="number"
                    min={1}
                    className="settings-input"
                    value={modelDraft.maxTokens}
                    onChange={(event) => setModelDraft((prev) => ({ ...prev, maxTokens: event.target.value }))}
                    placeholder="默认"
                  />
                </label>
                <label className="settings-model-field">
                  <span>Context Window</span>
                  <input
                    type="number"
                    min={1}
                    className="settings-input"
                    value={modelDraft.contextWindowTokens}
                    onChange={(event) => setModelDraft((prev) => ({ ...prev, contextWindowTokens: event.target.value }))}
                    placeholder="默认"
                  />
                </label>
                <label className="settings-model-field">
                  <span>Temperature</span>
                  <input
                    type="number"
                    step="0.1"
                    className="settings-input"
                    value={modelDraft.temperature}
                    onChange={(event) => setModelDraft((prev) => ({ ...prev, temperature: event.target.value }))}
                    placeholder="默认"
                  />
                </label>
                <label className="settings-model-field">
                  <span>Reasoning Effort</span>
                  <div className="settings-select-wrap">
                    <select
                      className="settings-select"
                      value={modelDraft.reasoningEffort}
                      onChange={(event) => setModelDraft((prev) => ({ ...prev, reasoningEffort: event.target.value }))}
                    >
                      <option value="">默认</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </div>
                </label>
                <div className="settings-model-field settings-model-inline">
                  <span>启用状态</span>
                  <label className="settings-switch">
                    <input
                      type="checkbox"
                      checked={modelDraft.enabled}
                      onChange={(event) => setModelDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                    />
                    <span />
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {mcpEditorOpen ? (
        <div className="settings-dialog-backdrop" onClick={() => setMcpEditorOpen(false)}>
          <div className="settings-dialog settings-model-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="settings-dialog-header">
              <div className="settings-dialog-heading">
                <p className="settings-shell-kicker">
                  {mcpDraft.id.startsWith("mcp_") ? "新建 MCP 服务" : "编辑 MCP 服务"}
                </p>
                <h2 className="settings-dialog-title">
                  {mcpDraft.name || "配置 MCP 服务"}
                </h2>
              </div>
              <div className="settings-list-actions">
                <button
                  type="button"
                  className="settings-icon-btn"
                  onClick={saveMcp}
                  title="保存"
                  aria-label="保存"
                >
                  <SaveIcon />
                </button>
                <button
                  type="button"
                  className="settings-icon-btn"
                  onClick={() => setMcpEditorOpen(false)}
                  title="关闭"
                  aria-label="关闭"
                >
                  <CloseIcon />
                </button>
              </div>
            </div>
            <div className="settings-dialog-body settings-model-body">
              {mcpEditorError ? <div className="settings-empty-card">{mcpEditorError}</div> : null}
              <div className="settings-model-grid">
                <label className="settings-model-field">
                  <span>名称</span>
                  <input
                    type="text"
                    className="settings-input"
                    value={mcpDraft.name}
                    onChange={(e) => setMcpDraft({ ...mcpDraft, name: e.target.value })}
                    placeholder="服务名称，如 Filesystem"
                  />
                </label>
                <label className="settings-model-field">
                  <span>通信协议</span>
                  <div className="settings-select-wrap">
                    <select
                      className="settings-select"
                      value={mcpDraft.transport}
                      onChange={(e) => setMcpDraft({ ...mcpDraft, transport: e.target.value })}
                    >
                      <option value="stdio">stdio (本地命令)</option>
                      <option value="streamableHttp">streamableHttp</option>
                      <option value="websocket">websocket</option>
                    </select>
                  </div>
                </label>
                <label className="settings-model-field settings-model-field-full">
                  <span>Endpoint / 指令</span>
                  <input
                    type="text"
                    className="settings-input settings-mono-input"
                    value={mcpDraft.endpoint}
                    onChange={(e) => setMcpDraft({ ...mcpDraft, endpoint: e.target.value })}
                    placeholder="npx @modelcontextprotocol/server-filesystem"
                  />
                </label>
                <div className="settings-model-field settings-model-inline">
                  <span>启用状态</span>
                  <label className="settings-switch">
                    <input
                      type="checkbox"
                      checked={mcpDraft.enabled}
                      onChange={(e) => setMcpDraft({ ...mcpDraft, enabled: e.target.checked })}
                    />
                    <span />
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default SettingsPage;
