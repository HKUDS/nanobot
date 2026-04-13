import React, { useState, useEffect, useRef } from "react";
import {
  ClockIcon,
  SearchIcon,
  SettingsIcon,
  CodexIcon,
  ProjectIcon,
  SparklesIcon,
  BoxIcon,
  MoreHorizontalIcon,
  ArrowRightIcon,
  ChevronDownIcon,
  DownloadIcon,
  GlobeIcon,
  InfoIcon,
} from "./Icons";

interface SidebarProps {
  isOpen: boolean;
  onNewChat: () => void;
  onSelectSession: (key: string) => void;
  onDeleteSession: (key: string) => void;
  onOpenCron: () => void;
  onOpenSettings: () => void;
  currentSessionKey: string;
  connected: boolean;
  gatewayUrl: string;
  currentView: "chat" | "cron" | "settings";
}

interface SessionItem {
  key: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
}

interface SessionPreference {
  customName?: string;
  pinned?: boolean;
}

const SESSION_PREFS_STORAGE_KEY = "nanobot_desktop_session_prefs";

const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onOpenCron,
  onOpenSettings,
  currentSessionKey,
  connected,
  gatewayUrl,
  currentView,
}) => {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [searchQuery] = useState("");
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [sessionPrefs, setSessionPrefs] = useState<Record<string, SessionPreference>>(() => {
    try {
      const raw = localStorage.getItem(SESSION_PREFS_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const [sessionMenuKey, setSessionMenuKey] = useState<string | null>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const sessionMenuRef = useRef<HTMLDivElement>(null);

  const httpUrl = gatewayUrl.replace("ws://", "http://").replace("wss://", "https://");

  // Fetch sessions
  useEffect(() => {
    if (!connected) return;
    const fetchSessions = async () => {
      try {
        const res = await fetch(`${httpUrl}/api/sessions`);
        if (res.ok) {
          const data = await res.json();
          setSessions(data.sessions || []);
        }
      } catch {
        // Failed to fetch sessions
      }
    };
    fetchSessions();
    const interval = setInterval(fetchSessions, 15000);
    return () => clearInterval(interval);
  }, [connected, httpUrl]);

  useEffect(() => {
    if (!profileMenuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!profileMenuRef.current?.contains(event.target as Node)) {
        setProfileMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setProfileMenuOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [profileMenuOpen]);

  useEffect(() => {
    try {
      localStorage.setItem(SESSION_PREFS_STORAGE_KEY, JSON.stringify(sessionPrefs));
    } catch {
      // ignore storage errors
    }
  }, [sessionPrefs]);

  useEffect(() => {
    if (!sessionMenuKey) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!sessionMenuRef.current?.contains(event.target as Node)) {
        setSessionMenuKey(null);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSessionMenuKey(null);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [sessionMenuKey]);

  const filteredSessions = [...sessions]
    .filter((s) => (searchQuery ? s.key.toLowerCase().includes(searchQuery.toLowerCase()) : true))
    .sort((a, b) => {
      const aPinned = sessionPrefs[a.key]?.pinned ? 1 : 0;
      const bPinned = sessionPrefs[b.key]?.pinned ? 1 : 0;
      if (aPinned !== bPinned) return bPinned - aPinned;
      const aTime = new Date(a.updated_at || a.created_at || 0).getTime();
      const bTime = new Date(b.updated_at || b.created_at || 0).getTime();
      return bTime - aTime;
    });

  const formatSessionName = (key: string): string => {
    const customName = sessionPrefs[key]?.customName?.trim();
    if (customName) return customName;
    const sessionTitle = sessions.find((item) => item.key === key)?.title?.trim();
    if (sessionTitle) return sessionTitle;
    const parts = key.split(":");
    const id = parts.length > 1 ? parts[1] : key;
    if (id === "direct") return "默认对话";
    if (/^\d+$/.test(id)) {
      const date = new Date(parseInt(id));
      if (!isNaN(date.getTime())) {
        return date.toLocaleDateString("zh-CN", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      }
    }
    return id.slice(0, 20);
  };

  const handleDelete = (e: React.MouseEvent, key: string) => {
    e.stopPropagation();
    onDeleteSession(key);
    setSessions((prev) => prev.filter((s) => s.key !== key));
    setSessionPrefs((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setSessionMenuKey(null);
  };

  const handleRenameSession = (key: string) => {
    const currentName = formatSessionName(key);
    const nextName = window.prompt("输入新的会话名称", currentName)?.trim();
    if (!nextName) {
      setSessionMenuKey(null);
      return;
    }
    setSessionPrefs((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        customName: nextName,
      },
    }));
    setSessionMenuKey(null);
  };

  const handleTogglePinSession = (key: string) => {
    setSessionPrefs((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        pinned: !prev[key]?.pinned,
      },
    }));
    setSessionMenuKey(null);
  };

  const navItems = [
    { key: "new", label: "New chat", icon: <span className="sidebar-nav-plus">+</span>, onClick: onNewChat },
    { key: "search", label: "Search", icon: <SearchIcon /> },
    { key: "customize", label: "设置", icon: <SettingsIcon />, onClick: onOpenSettings, active: currentView === "settings" },
    { key: "cron", label: "定时任务", icon: <ClockIcon />, onClick: onOpenCron, active: currentView === "cron" },
    { key: "projects", label: "Projects", icon: <ProjectIcon /> },
    { key: "artifacts", label: "Work", icon: <SparklesIcon /> },
    { key: "code", label: "Code", icon: <CodexIcon /> },
  ];

  return (
    <aside className={`sidebar ${isOpen ? "sidebar-open" : "sidebar-closed"}`}>
      <div className="sidebar-top">
        <div className="sidebar-nav">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={`sidebar-nav-item sidebar-nav-item-plain ${item.active ? "active" : ""}`}
              onClick={item.onClick}
              type="button"
            >
              <span className="sidebar-nav-icon">{item.icon}</span>
              <span className="sidebar-nav-label">{item.label}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-history">
          <div className="sidebar-history-label">Recents</div>
          {filteredSessions.length === 0 ? (
            <div className="sidebar-empty">暂无对话</div>
          ) : (
            filteredSessions.map((session) => (
              <div key={session.key} className="sidebar-session-row">
                <div
                  className={`sidebar-session-item ${currentView === "chat" && session.key === currentSessionKey ? "active" : ""}`}
                  onClick={() => onSelectSession(session.key)}
                  title={session.key}
                >
                  <span className="sidebar-session-name">
                    {sessionPrefs[session.key]?.pinned ? "置顶 · " : ""}
                    {formatSessionName(session.key)}
                  </span>
                  <button
                    className={`sidebar-session-delete ${sessionMenuKey === session.key ? "open" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSessionMenuKey((prev) => (prev === session.key ? null : session.key));
                    }}
                    title="更多操作"
                    type="button"
                  >
                    <MoreHorizontalIcon />
                  </button>
                </div>
                {sessionMenuKey === session.key ? (
                  <div className="sidebar-session-menu" ref={sessionMenuRef}>
                    <button className="sidebar-session-menu-item" type="button" onClick={() => handleRenameSession(session.key)}>
                      重命名
                    </button>
                    <button className="sidebar-session-menu-item" type="button" onClick={() => handleTogglePinSession(session.key)}>
                      {sessionPrefs[session.key]?.pinned ? "取消置顶" : "置顶"}
                    </button>
                    <button className="sidebar-session-menu-item danger" type="button" onClick={(e) => handleDelete(e, session.key)}>
                      删除
                    </button>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-bottom">
        <div className="sidebar-profile-wrap" ref={profileMenuRef}>
          {profileMenuOpen ? (
            <div className="sidebar-profile-menu">
              <div className="sidebar-profile-menu-email">nanobot@desktop.local</div>
              <button className="sidebar-profile-menu-item" onClick={onOpenSettings} type="button">
                <span className="sidebar-profile-menu-icon"><SettingsIcon /></span>
                <span className="sidebar-profile-menu-label">Settings</span>
              </button>
              <button className="sidebar-profile-menu-item" type="button">
                <span className="sidebar-profile-menu-icon"><GlobeIcon /></span>
                <span className="sidebar-profile-menu-label">Language</span>
                <span className="sidebar-profile-menu-trailing"><ArrowRightIcon /></span>
              </button>
              <button className="sidebar-profile-menu-item" type="button">
                <span className="sidebar-profile-menu-icon"><InfoIcon /></span>
                <span className="sidebar-profile-menu-label">Get help</span>
              </button>
              <button className="sidebar-profile-menu-upgrade" type="button">
                Upgrade plan
              </button>
              <button className="sidebar-profile-menu-item" type="button">
                <span className="sidebar-profile-menu-icon"><ClockIcon /></span>
                <span className="sidebar-profile-menu-label">Get apps and extensions</span>
              </button>
              <button className="sidebar-profile-menu-item" type="button">
                <span className="sidebar-profile-menu-icon"><SparklesIcon /></span>
                <span className="sidebar-profile-menu-label">Gift Claude</span>
              </button>
              <button className="sidebar-profile-menu-item" type="button">
                <span className="sidebar-profile-menu-icon"><InfoIcon /></span>
                <span className="sidebar-profile-menu-label">Learn more</span>
                <span className="sidebar-profile-menu-trailing"><ArrowRightIcon /></span>
              </button>
              <div className="sidebar-profile-menu-divider" />
              <button className="sidebar-profile-menu-item danger" type="button">
                <span className="sidebar-profile-menu-icon"><BoxIcon /></span>
                <span className="sidebar-profile-menu-label">Log out</span>
              </button>
            </div>
          ) : null}

          <div className="sidebar-profile">
            <button
              className={`sidebar-profile-trigger ${profileMenuOpen ? "open" : ""}`}
              type="button"
              onClick={() => setProfileMenuOpen((prev) => !prev)}
            >
              <div className="sidebar-profile-avatar">N</div>
              <div className="sidebar-profile-meta">
                <span className="sidebar-profile-name">nanobot</span>
                <span className="sidebar-profile-plan">{connected ? "已连接" : "未连接"}</span>
              </div>
            </button>
            <button className="sidebar-profile-utility" type="button" title="获取应用与扩展">
              <DownloadIcon />
            </button>
            <button
              className={`sidebar-profile-chevron ${profileMenuOpen ? "open" : ""}`}
              type="button"
              title="打开账户菜单"
              onClick={() => setProfileMenuOpen((prev) => !prev)}
            >
              <ChevronDownIcon />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
