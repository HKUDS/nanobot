import { useState } from "react";

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

function ConnectionPreview() {
  const [status, setStatus] = useState<ConnectionStatus>("open");
  return <><StatePicker label="连接状态" value={status} options={["idle", "connecting", "open", "reconnecting", "closed", "error"]} onChange={setStatus} />
    <div className="flex items-center gap-3"><ConnectionBadge status={status} /><span className="text-sm">{status}</span></div></>;
}

function HostPickerPreview() {
  const [mode, setMode] = useState<"ready" | "pending" | "offline" | "collapsed">("ready");
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [action, setAction] = useState("");
  const profiles: HostPicker["profiles"] = [
    { id: "gallery-development", name: "开发主机", host: "developer@dev.example", state: "open" },
    { id: "gallery-build", name: "构建主机", host: "builder@build.example", state: "closed" },
  ];
  const selected = profiles.find((profile) => profile.id === currentId);
  const picker: HostPicker = {
    kind: "shell", name: selected?.name ?? "本机", hostname: selected?.host ?? "gallery", localName: "gallery",
    currentId, profiles, recentIds: [], pending: mode === "pending" ? { id: profiles[0].id, name: profiles[0].name } : null,
    error: mode === "offline" ? "示例主机已断开。" : "", offline: mode === "offline",
    select: (id) => { setCurrentId(id); setMode("ready"); }, manage: () => setAction("打开连接管理"),
    cancel: () => { setMode("ready"); setAction("已取消示例切换"); }, clearError: () => setMode("ready"), restoreFocus: () => {},
  };
  return <><StatePicker label="主机菜单状态" value={mode} options={["ready", "pending", "offline", "collapsed"]} onChange={setMode} />
    <div className="max-w-sm rounded-panel bg-sidebar p-4"><HostSwitcherView picker={picker} status="open" collapsed={mode === "collapsed"} /></div>
    <p role="status" className="mt-4 text-sm text-muted-foreground">{action || `预览中的主机：${picker.name}`}</p></>;
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
  const [sessions, setSessions] = useState(initialSessions);
  const [active, setActive] = useState<string | null>(initialSessions[0].key);
  const [pinned, setPinned] = useState<string[]>([]);
  const [archived, setArchived] = useState<string[]>(["websocket:gallery-history"]);
  const [mode, setMode] = useState<"ready" | "loading" | "empty" | "archived">("ready");
  const [action, setAction] = useState("");
  const toggle = (keys: string[], key: string) => keys.includes(key) ? keys.filter((value) => value !== key) : [...keys, key];
  return <><StatePicker label="会话列表状态" value={mode} options={["ready", "loading", "empty", "archived"]} onChange={setMode} />
    <div className="flex h-80 max-w-sm flex-col rounded-panel bg-sidebar p-2"><ChatList sessions={mode === "loading" || mode === "empty" ? [] : sessions}
      activeKey={active} onSelect={setActive} pinnedKeys={pinned} archivedKeys={archived} showArchived={mode === "archived"}
      loading={mode === "loading"}
      onTogglePin={(key) => setPinned(toggle(pinned, key))} onToggleArchive={(key) => setArchived(toggle(archived, key))}
      onRequestDelete={(key) => setSessions((items) => items.filter((item) => item.key !== key))}
      onRequestRename={(_, label) => setAction(`选择重命名：${label}`)} /></div>
    <p role="status" className="mt-4 text-sm text-muted-foreground">{action || `选择的会话：${active ?? "无"}`}</p></>;
}

function SidebarResizePreview() {
  const [width, setWidth] = useState(260);
  const [open, setOpen] = useState(true);
  const [dragging, setDragging] = useState(false);
  return <div className="space-y-4"><div className="relative flex h-72 overflow-hidden rounded-panel border">
    <aside id="main-sidebar" className="relative shrink-0 bg-sidebar p-4" style={{ width: open ? width : 56 }}>
      {open ? <p className="text-sm text-muted-foreground">侧栏内容</p> : null}
      <SidebarResizeHandle width={width} open={open} onResize={(next, expanded) => { setWidth(next); setOpen(expanded); }} onDraggingChange={setDragging} />
    </aside><div className="min-w-0 flex-1 p-4 text-sm text-muted-foreground">拖动分隔条，或聚焦后使用方向键、Home、End 和 Enter。</div>
  </div><p role="status" className="text-sm text-muted-foreground">{open ? `${width}px` : "已收起"}{dragging ? " · 正在拖动" : ""}</p></div>;
}

function ChannelMarksPreview() {
  const [name, setName] = useState<"Nanobot" | "研发">("Nanobot");
  return <><StatePicker label="头像名称" value={name} options={["Nanobot", "研发"]} onChange={setName} />
    <div className="flex items-start gap-8"><Sample label="成员头像"><LinearAvatar name={name} /></Sample>
      <Sample label="工作区图标"><LinearAvatar name={name} workspace /></Sample><Sample label="WebSocket"><WebSocketIcon /></Sample></div></>;
}

function SecretPreview() {
  const [mode, setMode] = useState<"new" | "saved" | "disabled" | "error">("new");
  const [configured, setConfigured] = useState(false);
  return <><StatePicker label="密钥状态" value={mode} options={["new", "saved", "disabled", "error"]}
    onChange={(next) => { setMode(next); setConfigured(next === "saved"); }} />
    <LinearSecretField field={{ key: "api_key", label: "API Key", secret: true }} configured={configured} disabled={mode === "disabled"}
      onSave={async () => { if (mode === "error") throw new Error("Example save failed"); setConfigured(true); }} />
    <p className="mt-4 text-xs text-muted-foreground">输入示例文本并保存，或切换错误状态检查草稿保留。</p></>;
}

function ChannelHelpPreview() {
  return <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline">打开频道帮助</Button></DropdownMenuTrigger>
    <DropdownMenuContent><LinearHelpContent /><DropdownMenuItem>关闭</DropdownMenuItem></DropdownMenuContent></DropdownMenu>;
}

const components = "webui/src/components/";
export const standaloneExamples: ComponentExample[] = [
  { title: "ConnectionBadge · 连接指示", files: [`${components}ConnectionBadge.tsx`], Preview: ConnectionPreview,
    description: "切换连接状态，查看颜色、动画和可访问状态文字。", options: "status 来自调用方。连接订阅由页面容器维护。",
    code: '<ConnectionBadge status={status} />' },
  { title: "HostSwitcherView · 主机菜单", files: [`${components}remote/HostSwitcherView.tsx`], Preview: HostPickerPreview,
    description: "打开主机菜单，选择本机或示例主机，并切换待连接、断开和收起状态。", options: "picker 提供主机显示数据与操作回调；status 是当前连接状态。生产 HostSwitcher 负责订阅客户端。",
    code: '<HostSwitcherView picker={picker} status="open" collapsed={false} />' },
  { title: "ChatList · 会话列表", files: [`${components}ChatList.tsx`, `${components}SidebarSelectionHighlight.tsx`], Preview: ChatsPreview,
    description: "选择会话，打开操作菜单，试用置顶、归档和删除。", options: "sessions、activeKey 和已置顶/归档的 key 由调用方提供。各操作通过回调更新示例列表。",
    code: '<ChatList sessions={sessions} activeKey={active} onSelect={setActive} onTogglePin={pin} onToggleArchive={archive} onRequestDelete={remove} onRequestRename={rename} />' },
  { title: "SidebarResizeHandle · 侧栏尺寸", files: [`${components}SidebarResizeHandle.tsx`], Preview: SidebarResizePreview,
    description: "用鼠标或键盘调整侧栏宽度并收起或展开。", options: "width 与 open 是受控状态；onResize 更新尺寸与展开状态；onDraggingChange 通知拖动状态。",
    code: '<SidebarResizeHandle width={width} open={open} onResize={resize} onDraggingChange={setDragging} />' },
  { title: "LanguageSwitcher · 界面语言", files: [`${components}LanguageSwitcher.tsx`], Preview: LanguageSwitcher,
    description: "切换画廊内生产组件使用的界面语言。", options: "使用应用已有 i18n 与浏览器语言偏好，不需要 gateway。顶部语言选择器使用同一个组件。",
    code: '<LanguageSwitcher />' },
  { title: "Channel marks · 频道标识", files: ["nanobot/channels/linear/webui/LinearAvatar.tsx", "nanobot/channels/websocket/webui/WebSocketIcon.tsx"], Preview: ChannelMarksPreview,
    description: "查看成员头像缺省文字、工作区图标和 WebSocket 标识。", options: "LinearAvatar 接收 name、url 和 workspace；无有效图片时显示缺省文字或图标。",
    code: '<LinearAvatar name="Nanobot" />\n<LinearAvatar name="Nanobot" workspace />\n<WebSocketIcon />' },
  { title: "LinearSecretField · 密钥编辑", files: ["nanobot/channels/linear/webui/LinearSecretField.tsx"], Preview: SecretPreview,
    description: "编辑、显示、保存与替换密钥，检查保存失败时的输入保留。", options: "configured 是已保存状态，onSave 负责持久化。画廊回调仅更新本地状态。",
    code: '<LinearSecretField field={field} configured={configured} disabled={false} onSave={save} />' },
  { title: "LinearHelpContent · 频道帮助", files: ["nanobot/channels/linear/webui/LinearHelpContent.tsx"], Preview: ChannelHelpPreview,
    description: "在实际下拉菜单中查看频道帮助内容。", options: "内容使用频道的现有翻译，菜单容器由调用方提供。",
    code: '<DropdownMenuContent><LinearHelpContent /></DropdownMenuContent>' },
];
