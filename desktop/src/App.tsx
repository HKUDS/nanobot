import { useState, useCallback, useEffect, type MouseEvent } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Sidebar from "@/components/Sidebar";
import ChatMain from "@/components/ChatMain";
import CronPage from "@/components/CronPage";
import SettingsPage from "@/components/SettingsPage";
import type { AppearanceSettings } from "@/components/SettingsPage";
import { ArrowLeftIcon, ArrowRightIcon, BotFaceIcon, SidebarIcon } from "@/components/Icons";
import { useChat } from "@/hooks/useChat";

type ViewMode = "chat" | "cron" | "settings";

const defaultAppearance: AppearanceSettings = {
  theme: "system",
  bubbleStyle: "rounded",
  fontScale: "medium",
  motionLevel: "balanced",
  compactMode: false,
};

const readAppearance = (): AppearanceSettings => {
  try {
    const raw = localStorage.getItem("nanobot_desktop_appearance");
    return raw ? { ...defaultAppearance, ...JSON.parse(raw) } : defaultAppearance;
  } catch {
    return defaultAppearance;
  }
};

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [currentSessionKey, setCurrentSessionKey] = useState("desktop:direct");
  const [appearance, setAppearance] = useState<AppearanceSettings>(() => readAppearance());
  const [resolvedTheme, setResolvedTheme] = useState<"dark" | "light">("dark");
  const [titlebarDragging, setTitlebarDragging] = useState(false);
  const [activeModelLabel, setActiveModelLabel] = useState("nanobot");
  const [activeProviderLabel, setActiveProviderLabel] = useState("");
  const [modelOptions, setModelOptions] = useState<Array<{ id: string; name: string; enabled: boolean; provider: string }>>([]);
  const [defaultModelId, setDefaultModelId] = useState("");
  const [currentSessionModelId, setCurrentSessionModelId] = useState("");
  const [providerLabels, setProviderLabels] = useState<Record<string, string>>({});
  const [switchingModel, setSwitchingModel] = useState(false);
  const [modelSwitchFeedback, setModelSwitchFeedback] = useState("");
  const [gatewayUrl, setGatewayUrl] = useState(() => {
    return localStorage.getItem("nanobot_gateway_url") || "ws://localhost:18790";
  });
  const httpUrl = gatewayUrl.replace("ws://", "http://").replace("wss://", "https://");

  const chat = useChat({
    gatewayUrl,
    sessionKey: currentSessionKey,
    modelId: currentSessionModelId || defaultModelId,
  });

  const toggleSidebar = () => setSidebarOpen((prev) => !prev);
  const canToolbarBack = viewMode !== "chat" || sidebarOpen;
  const canToolbarForward = viewMode === "chat" && !sidebarOpen;
  const handleToolbarBack = useCallback(() => {
    if (viewMode !== "chat") {
      setViewMode("chat");
      return;
    }
    if (sidebarOpen) {
      setSidebarOpen(false);
    }
  }, [sidebarOpen, viewMode]);
  const handleToolbarForward = useCallback(() => {
    if (viewMode === "chat" && !sidebarOpen) {
      setSidebarOpen(true);
    }
  }, [sidebarOpen, viewMode]);

  const handleNewChat = useCallback(() => {
    const key = `desktop:${Date.now()}`;
    setCurrentSessionKey(key);
    setCurrentSessionModelId(defaultModelId);
    setViewMode("chat");
    chat.clearMessages();
  }, [chat, defaultModelId]);

  const handleSelectSession = useCallback(
    async (key: string) => {
      setCurrentSessionKey(key);
      setViewMode("chat");
      const session = await chat.loadSession(key);
      setCurrentSessionModelId(session?.modelId || defaultModelId);
    },
    [chat, defaultModelId]
  );

  const handleDeleteSession = useCallback(
    async (key: string) => {
      const httpUrl = gatewayUrl.replace("ws://", "http://").replace("wss://", "https://");
      const safeKey = key.replace(":", "__");
      try {
        await fetch(`${httpUrl}/api/sessions/${safeKey}`, { method: "DELETE" });
      } catch {
        // ignore
      }
      if (key === currentSessionKey) {
        setCurrentSessionKey("desktop:direct");
        setCurrentSessionModelId(defaultModelId);
        chat.clearMessages();
      }
    },
    [gatewayUrl, currentSessionKey, chat, defaultModelId]
  );

  const handleGatewayUrlChange = useCallback((url: string) => {
    setGatewayUrl(url);
    localStorage.setItem("nanobot_gateway_url", url);
    // Force page reload to reconnect WebSocket with new URL
    window.location.reload();
  }, []);

  useEffect(() => {
    localStorage.setItem("nanobot_desktop_appearance", JSON.stringify(appearance));

    const root = document.documentElement;
    root.dataset.fontScale = appearance.fontScale;
    root.dataset.motionLevel = appearance.motionLevel;
    root.dataset.bubbleStyle = appearance.bubbleStyle;
    root.dataset.themePreference = appearance.theme;

    root.classList.toggle("compact-mode", appearance.compactMode);
  }, [appearance]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const nextTheme =
        appearance.theme === "system"
          ? media.matches
            ? "dark"
            : "light"
          : appearance.theme === "light"
            ? "light"
            : "dark";

      setResolvedTheme(nextTheme);
      document.documentElement.dataset.themeResolved = nextTheme;
    };

    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [appearance.theme]);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const [configResponse, modelsResponse] = await Promise.all([
          fetch(`${httpUrl}/api/config`),
          fetch(`${httpUrl}/api/models`),
        ]);
        if (!configResponse.ok) {
          setActiveModelLabel("nanobot");
          setActiveProviderLabel("");
          return;
        }
        const data = await configResponse.json();
        const nextLabel = data?.activeModel?.name || data?.model || "nanobot";
        const nextDefaultModelId = data?.defaultModelId || "";
        setActiveModelLabel(nextLabel);
        setActiveProviderLabel(data?.provider || "");
        setDefaultModelId(nextDefaultModelId);
        if (modelsResponse.ok) {
          const modelsData = await modelsResponse.json();
          setModelOptions((modelsData?.items || []).map((item: { id: string; name: string; enabled: boolean; provider: string }) => ({
            id: item.id,
            name: item.name,
            enabled: item.enabled,
            provider: item.provider,
          })));
          setProviderLabels(
            Object.fromEntries(((modelsData?.providers || []) as Array<{ id: string; label: string }>).map((item) => [item.id, item.label]))
          );
        }
        setCurrentSessionModelId((prev) => prev || nextDefaultModelId);
      } catch {
        setActiveModelLabel("nanobot");
        setActiveProviderLabel("");
        setModelOptions([]);
        setDefaultModelId("");
        setCurrentSessionModelId("");
        setProviderLabels({});
      }
    };

    void loadConfig();
    const onConfigChanged = () => void loadConfig();
    window.addEventListener("nanobot-config-changed", onConfigChanged);
    return () => window.removeEventListener("nanobot-config-changed", onConfigChanged);
  }, [gatewayUrl]);

  useEffect(() => {
    void (async () => {
      const session = await chat.loadSession(currentSessionKey);
      setCurrentSessionModelId(session?.modelId || defaultModelId);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const selectedModel = modelOptions.find((item) => item.id === (currentSessionModelId || defaultModelId));
    if (selectedModel) {
      setActiveModelLabel(selectedModel.name);
      setActiveProviderLabel(providerLabels[selectedModel.provider] || selectedModel.provider);
    }
  }, [currentSessionModelId, defaultModelId, modelOptions, providerLabels]);

  const handleQuickSwitchModel = useCallback(
    async (modelId: string) => {
      if (!modelId || modelId === currentSessionModelId) return;
      setSwitchingModel(true);
      setModelSwitchFeedback("");
      try {
        const safeKey = currentSessionKey.replace(":", "__");
        const response = await fetch(`${httpUrl}/api/sessions/${safeKey}/model`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ modelId: modelId || null }),
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          setModelSwitchFeedback(data.error || "切换模型失败");
          return;
        }
        const selected = modelOptions.find((item) => item.id === modelId);
        setCurrentSessionModelId(modelId);
        setModelSwitchFeedback(`已切换到 ${selected?.name || "新模型"}`);
      } catch {
        setModelSwitchFeedback("切换模型失败");
      } finally {
        setSwitchingModel(false);
      }
    },
    [currentSessionKey, currentSessionModelId, httpUrl, modelOptions]
  );

  const handleTitlebarMouseDown = useCallback((event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.closest("button, input, textarea, select, a, [role='button']")) return;
    setTitlebarDragging(true);
    void getCurrentWindow().startDragging();
  }, []);

  const handleTitlebarDoubleClick = useCallback((event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.closest("button, input, textarea, select, a, [role='button']")) return;
    void getCurrentWindow().toggleMaximize();
  }, []);

  useEffect(() => {
    if (!modelSwitchFeedback) return;
    const timer = window.setTimeout(() => {
      setModelSwitchFeedback("");
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [modelSwitchFeedback]);

  useEffect(() => {
    if (!titlebarDragging) return;
    const clearDragging = () => setTitlebarDragging(false);
    window.addEventListener("mouseup", clearDragging);
    window.addEventListener("blur", clearDragging);
    return () => {
      window.removeEventListener("mouseup", clearDragging);
      window.removeEventListener("blur", clearDragging);
    };
  }, [titlebarDragging]);

  return (
    <div className={`app-container theme-${resolvedTheme}`}>
      <div className="app-frame">
        <header
          className={`window-titlebar ${titlebarDragging ? "is-dragging" : ""}`}
          onMouseDown={handleTitlebarMouseDown}
          onDoubleClick={handleTitlebarDoubleClick}
        >
          <div className="window-titlebar-left">
            <div className="window-titlebar-traffic-space" />
            <button className="window-titlebar-btn" onClick={toggleSidebar} title={sidebarOpen ? "收起侧栏" : "打开侧栏"}>
              <SidebarIcon />
            </button>
            <div className="window-titlebar-divider" />
            <button
              className={`window-titlebar-btn ${canToolbarBack ? "" : "is-muted"}`}
              type="button"
              title={viewMode !== "chat" ? "返回聊天" : "收起侧栏"}
              onClick={handleToolbarBack}
              disabled={!canToolbarBack}
            >
              <ArrowLeftIcon />
            </button>
            <button
              className={`window-titlebar-btn ${canToolbarForward ? "" : "is-muted"}`}
              type="button"
              title="展开侧栏"
              onClick={handleToolbarForward}
              disabled={!canToolbarForward}
            >
              <ArrowRightIcon />
            </button>
          </div>
          <div className="window-titlebar-center" />
          <div className="window-titlebar-right">
            <button className="window-titlebar-btn" onClick={() => setViewMode("settings")} title="打开设置">
              <BotFaceIcon />
            </button>
          </div>
        </header>

        <div className="app-body">
          <Sidebar
            isOpen={sidebarOpen}
            onNewChat={handleNewChat}
            onSelectSession={handleSelectSession}
            onDeleteSession={handleDeleteSession}
            onOpenCron={() => setViewMode("cron")}
            onOpenSettings={() => setViewMode("settings")}
            currentSessionKey={currentSessionKey}
            connected={chat.connected}
            gatewayUrl={gatewayUrl}
            currentView={viewMode}
          />
          {viewMode === "chat" ? (
            <ChatMain
              sessionKey={currentSessionKey}
              messages={chat.messages}
              isLoading={chat.isLoading}
              progress={chat.progress}
              connected={chat.connected}
              onSend={chat.send}
              modelLabel={activeModelLabel}
              providerLabel={activeProviderLabel}
              modelOptions={modelOptions}
              selectedModelId={currentSessionModelId || defaultModelId}
              onSelectModel={handleQuickSwitchModel}
              modelSwitching={switchingModel}
            />
          ) : viewMode === "cron" ? (
            <CronPage gatewayUrl={gatewayUrl} />
          ) : (
            <SettingsPage
              gatewayUrl={gatewayUrl}
              onGatewayUrlChange={handleGatewayUrlChange}
              appearance={appearance}
              onAppearanceChange={setAppearance}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
