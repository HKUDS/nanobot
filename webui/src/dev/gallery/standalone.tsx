import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatList } from "@/components/ChatList";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SidebarResizeHandle } from "@/components/SidebarResizeHandle";
import { HostSwitcherView } from "@/components/remote/HostSwitcherView";
import type { HostPicker } from "@/components/remote/host-navigation";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { LinearAvatar } from "../../../../nanobot/channels/linear/webui/LinearAvatar";
import { LinearHelpContent } from "../../../../nanobot/channels/linear/webui/LinearHelpContent";
import { LinearSecretField } from "../../../../nanobot/channels/linear/webui/LinearSecretField";
import { WebSocketIcon } from "../../../../nanobot/channels/websocket/webui/WebSocketIcon";
import type { ChatSummary, ConnectionStatus } from "@/lib/types";
import { Sample, StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

function ConnectionPreview() {
  const { t } = useGalleryTranslation();
  const [status, setStatus] = useState<ConnectionStatus>("open");
  return <><StatePicker label={t("previews.connectionBadge.state")} value={status} options={["idle", "connecting", "open", "reconnecting", "closed", "error"]} onChange={setStatus} />
    <div className="flex items-center gap-3"><ConnectionBadge status={status} /><span className="text-sm">{t(`previews.connectionBadge.${status}`)}</span></div></>;
}

function HostPickerPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [mode, setMode] = useState<"ready" | "pending" | "offline" | "collapsed">("ready");
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [action, setAction] = useState("");
  const profiles: HostPicker["profiles"] = [
    { id: "gallery-development", name: "开发主机", host: "developer@dev.example", state: "open" },
    { id: "gallery-build", name: "构建主机", host: "builder@build.example", state: "closed" },
  ];
  const selected = profiles.find((profile) => profile.id === currentId);
  const picker: HostPicker = {
    kind: "shell", name: selected?.name ?? t("remote.local"), hostname: selected?.host ?? "gallery", localName: "gallery",
    currentId, profiles, recentIds: [], pending: mode === "pending" ? { id: profiles[0].id, name: profiles[0].name } : null,
    error: mode === "offline" ? g("previews.hostPicker.offline") : "", offline: mode === "offline",
    select: (id) => { setCurrentId(id); setMode("ready"); }, manage: () => setAction("previews.hostPicker.manage"),
    cancel: () => { setMode("ready"); setAction("previews.hostPicker.cancelled"); }, clearError: () => setMode("ready"), restoreFocus: () => {},
  };
  return <><StatePicker label={g("previews.hostPicker.state")} value={mode} options={["ready", "pending", "offline", "collapsed"]} onChange={setMode} />
    <div className="max-w-sm rounded-panel bg-sidebar p-4"><HostSwitcherView picker={picker} status="open" collapsed={mode === "collapsed"} /></div>
    <p role="status" className="mt-4 text-sm text-muted-foreground">{action ? g(action) : g("previews.hostPicker.selected", { name: picker.name })}</p></>;
}

const initialSessions: ChatSummary[] = [
  { key: "websocket:gallery-components", chatId: "gallery-components", channel: "websocket", title: "组件设计", preview: "模型选择、消息输入和设置表单。",
    createdAt: "2026-10-01T12:00:00Z", updatedAt: "2026-10-13T08:00:00Z", handle: { id: "gallery-components", name: "design" } },
  { key: "websocket:gallery-tests", chatId: "gallery-tests", channel: "websocket", title: "验证交互", preview: "检查错误状态与键盘操作。",
    createdAt: "2026-10-02T12:00:00Z", updatedAt: "2026-10-13T09:00:00Z", handle: { id: "gallery-tests", name: "tests" } },
  { key: "websocket:gallery-history", chatId: "gallery-history", channel: "websocket", title: "历史方案", preview: "已归档的会话示例。",
    createdAt: "2026-10-01T10:00:00Z", updatedAt: "2026-10-05T10:00:00Z", handle: { id: "gallery-history", name: "history" } },
];

function ChatsPreview() {
  const { t } = useGalleryTranslation();
  const [sessions, setSessions] = useState(initialSessions);
  const [active, setActive] = useState<string | null>(initialSessions[0].key);
  const [pinned, setPinned] = useState<string[]>([]);
  const [archived, setArchived] = useState<string[]>(["websocket:gallery-history"]);
  const [mode, setMode] = useState<"ready" | "loading" | "empty" | "archived">("ready");
  const [renamed, setRenamed] = useState<string | null>(null);
  const toggle = (keys: string[], key: string) => keys.includes(key) ? keys.filter((value) => value !== key) : [...keys, key];
  return <><StatePicker label={t("previews.chats.state")} value={mode} options={["ready", "loading", "empty", "archived"]} onChange={setMode} />
    <div className="flex h-80 max-w-sm flex-col rounded-panel bg-sidebar p-2"><ChatList sessions={mode === "loading" || mode === "empty" ? [] : sessions}
      activeKey={active} onSelect={setActive} pinnedKeys={pinned} archivedKeys={archived} showArchived={mode === "archived"}
      loading={mode === "loading"}
      onTogglePin={(key) => setPinned(toggle(pinned, key))} onToggleArchive={(key) => setArchived(toggle(archived, key))}
      onRequestDelete={(key, _label, onDecision) => {
        onDecision?.(true);
        setSessions((items) => items.filter((item) => item.key !== key));
      }}
      onRequestDeleteMany={(items, onDecision) => {
        onDecision?.(true);
        const keys = new Set(items.map((item) => item.key));
        setSessions((current) => current.filter((item) => !keys.has(item.key)));
      }}
      onRequestRename={async (key, label) => {
        setSessions((items) => items.map((item) => item.key === key ? { ...item, title: label } : item));
        setRenamed(label);
      }} /></div>
    <p role="status" className="mt-4 text-sm text-muted-foreground">{renamed !== null ? t("previews.chats.renamed", { name: renamed })
      : t("previews.chats.selected", { name: active ?? t("previews.chats.none") })}</p></>;
}

function SidebarResizePreview() {
  const { t } = useGalleryTranslation();
  const [width, setWidth] = useState(260);
  const [open, setOpen] = useState(true);
  const [dragging, setDragging] = useState(false);
  return <div className="space-y-4"><div className="relative flex h-72 overflow-hidden rounded-panel border">
    <aside id="main-sidebar" className="relative shrink-0 bg-sidebar p-4" style={{ width: open ? width : 56 }}>
      {open ? <p className="text-sm text-muted-foreground">{t("previews.sidebarResize.content")}</p> : null}
      <SidebarResizeHandle width={width} open={open} onResize={(next, expanded) => { setWidth(next); setOpen(expanded); }} onDraggingChange={setDragging} />
    </aside><div className="min-w-0 flex-1 p-4 text-sm text-muted-foreground">{t("previews.sidebarResize.hint")}</div>
  </div><p role="status" className="text-sm text-muted-foreground">{open ? `${width}px` : t("previews.sidebarResize.collapsed")}{dragging ? ` · ${t("previews.sidebarResize.dragging")}` : ""}</p></div>;
}

function ChannelMarksPreview() {
  const { t } = useGalleryTranslation();
  const [name, setName] = useState<"Nanobot" | "研发">("Nanobot");
  return <><StatePicker label={t("previews.channelMarks.name")} value={name} options={["Nanobot", "研发"]} onChange={setName} />
    <div className="flex items-start gap-8"><Sample label={t("previews.channelMarks.member")}><LinearAvatar name={name} /></Sample>
      <Sample label={t("previews.channelMarks.workspace")}><LinearAvatar name={name} workspace /></Sample><Sample label="WebSocket"><WebSocketIcon /></Sample></div></>;
}

function SecretPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [mode, setMode] = useState<"new" | "saved" | "disabled" | "error">("new");
  const [configured, setConfigured] = useState(false);
  return <><StatePicker label={g("previews.secret.state")} value={mode} options={["new", "saved", "disabled", "error"]}
    onChange={(next) => { setMode(next); setConfigured(next === "saved"); }} />
    <LinearSecretField field={{ key: "api_key", label: t("settings.byok.apiKey"), secret: true }} configured={configured} disabled={mode === "disabled"}
      onSave={async () => { if (mode === "error") throw new Error(g("previews.secret.error")); setConfigured(true); }} />
    <p className="mt-4 text-xs text-muted-foreground">{g("previews.secret.hint")}</p></>;
}

function ChannelHelpPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  return <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline">{g("previews.channelHelp.open")}</Button></DropdownMenuTrigger>
    <DropdownMenuContent><LinearHelpContent /><DropdownMenuItem>{t("common.close")}</DropdownMenuItem></DropdownMenuContent></DropdownMenu>;
}

const components = "webui/src/components/";
export const standaloneExamples: ComponentExample[] = [
  { title: "previews.connectionBadge.title", files: [`${components}ConnectionBadge.tsx`], Preview: ConnectionPreview,
    description: "previews.connectionBadge.description", options: "previews.connectionBadge.options",
    code: '<ConnectionBadge status={status} />' },
  { title: "previews.hostPicker.title", files: [`${components}remote/HostSwitcherView.tsx`], Preview: HostPickerPreview,
    description: "previews.hostPicker.description", options: "previews.hostPicker.options",
    code: '<HostSwitcherView picker={picker} status="open" collapsed={false} />' },
  { title: "previews.chats.title", files: [`${components}ChatList.tsx`, `${components}SidebarSelectionHighlight.tsx`], Preview: ChatsPreview,
    description: "previews.chats.description", options: "previews.chats.options",
    code: '<ChatList sessions={sessions} activeKey={active} onSelect={setActive} onTogglePin={pin} onToggleArchive={archive} onRequestDelete={remove} onRequestRename={rename} />' },
  { title: "previews.sidebarResize.title", files: [`${components}SidebarResizeHandle.tsx`], Preview: SidebarResizePreview,
    description: "previews.sidebarResize.description", options: "previews.sidebarResize.options",
    code: '<SidebarResizeHandle width={width} open={open} onResize={resize} onDraggingChange={setDragging} />' },
  { title: "previews.language.title", files: [`${components}LanguageSwitcher.tsx`], Preview: LanguageSwitcher,
    description: "previews.language.description", options: "previews.language.options",
    code: '<LanguageSwitcher />' },
  { title: "previews.channelMarks.title", files: ["nanobot/channels/linear/webui/LinearAvatar.tsx", "nanobot/channels/websocket/webui/WebSocketIcon.tsx"], Preview: ChannelMarksPreview,
    description: "previews.channelMarks.description", options: "previews.channelMarks.options",
    code: '<LinearAvatar name="Nanobot" />\n<LinearAvatar name="Nanobot" workspace />\n<WebSocketIcon />' },
  { title: "previews.secret.title", files: ["nanobot/channels/linear/webui/LinearSecretField.tsx"], Preview: SecretPreview,
    description: "previews.secret.description", options: "previews.secret.options",
    code: '<LinearSecretField field={field} configured={configured} disabled={false} onSave={save} />' },
  { title: "previews.channelHelp.title", files: ["nanobot/channels/linear/webui/LinearHelpContent.tsx"], Preview: ChannelHelpPreview,
    description: "previews.channelHelp.description", options: "previews.channelHelp.options",
    code: '<DropdownMenuContent><LinearHelpContent /></DropdownMenuContent>' },
];
