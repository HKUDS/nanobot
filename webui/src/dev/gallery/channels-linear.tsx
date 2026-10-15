import { useState } from "react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
import { defaultChannelFieldValues } from "@/components/settings/channels/CredentialForm";
import type { ChannelConnectPayload, NanobotFeatureInfo } from "@/lib/types";
import { LinearPanelView } from "../../../../nanobot/channels/linear/webui/LinearPanelView";
import { LinearMemberAccessView, type LinearMemberAccessSnapshot } from "../../../../nanobot/channels/linear/webui/LinearMemberAccessView";
import { LinearConnectFlowView, linearConnectLabels } from "../../../../nanobot/channels/linear/webui/LinearConnectFlowView";
import { LinearResetConnectionView } from "../../../../nanobot/channels/linear/webui/LinearResetConnectionView";
import type { LinearInstallationSummary } from "../../../../nanobot/channels/linear/webui/types";
import { channelFeatures } from "./channel-fixtures";
import { StatePicker, type ComponentExample } from "./example";

const workspace: LinearInstallationSummary = {
  organization_id: "gallery-workspace", organization_name: "Nanobot team",
  scopes: ["read", "write", "app:assignable", "app:mentionable"], authorization_status: "authorized",
};

type MemberStory = "members" | "loading" | "refreshing" | "empty" | "error" | "saving" | "save-error" | "allow-all";

function memberSnapshot(story: MemberStory): LinearMemberAccessSnapshot {
  const members = [
    { id: "gallery-alex", name: "Alex", teams: ["Engineering"], allowed: true },
    { id: "gallery-robin", name: "Robin", teams: ["Design"], allowed: false },
    { id: "gallery-alex-two", name: "Alex", teams: ["Support"], allowed: false },
  ];
  return {
    payload: story === "loading" || story === "error" ? null : {
      session_id: "gallery-members", status: "members", organization_id: workspace.organization_id,
      legacy_allow_all: story === "allow-all", members: story === "empty" ? [] : members,
    },
    loading: story === "loading" || story === "refreshing",
    error: story === "error" ? "Member directory is unavailable." : null,
    saves: story === "saving" ? { "gallery-alex": { status: "saving" } }
      : story === "save-error" ? { "gallery-alex": { status: "error", message: "Access was not confirmed." } } : {},
  };
}

function MemberList({ story = "members", disabled = false }: { story?: MemberStory; disabled?: boolean }) {
  const [snapshot, setSnapshot] = useState(() => memberSnapshot(story));
  return <LinearMemberAccessView snapshot={snapshot} disabled={disabled}
    onLoad={(force) => { if (force) setSnapshot(memberSnapshot("members")); }}
    onSetAllowed={(id, allowed) => setSnapshot(current => ({ ...current,
      payload: current.payload ? { ...current.payload,
        members: current.payload.members.map(member => member.id === id ? { ...member, allowed } : member),
      } : null,
      saves: { ...current.saves, [id]: { status: "saved" } },
    }))} />;
}

function MembersPreview() {
  const [story, setStory] = useState<MemberStory>("members");
  return <><StatePicker label="成员状态" value={story}
    options={["members", "loading", "refreshing", "empty", "error", "saving", "save-error", "allow-all"]}
    onChange={setStory} /><div className="overflow-hidden rounded-panel border border-border/70">
    <MemberList key={story} story={story} /></div></>;
}

type ConnectStory = "idle" | "starting" | "pending" | "succeeded" | "cancelled" | "failed";
function connection(story: ConnectStory): ChannelConnectPayload | null {
  if (story === "idle" || story === "starting") return null;
  return { session_id: "gallery-linear-authorization", status: story,
    qr_url: story === "pending" ? "https://linear.app/oauth/authorize?client_id=gallery-example" : undefined,
  };
}

function AuthorizationPreview() {
  const { t } = useTranslation();
  const [story, setStory] = useState<ConnectStory>("idle");
  const connect = connection(story);
  return <><StatePicker label="授权阶段" value={story}
    options={["idle", "starting", "pending", "succeeded", "cancelled", "failed"]} onChange={setStory} />
    <LinearConnectFlowView connect={connect} busy={story === "starting"} error={story === "failed" ? "Authorization could not be completed." : null}
      labels={linearConnectLabels(channelTranslator(t, "linear"))}
      onStart={() => setStory("pending")} onCancel={() => setStory("cancelled")}
      onPoll={async () => connect} />
    <p className="mt-4 text-xs text-muted-foreground">授权链接与工作区为示例数据；开始、取消只更新预览阶段。</p></>;
}

type ResetStory = "success" | "partial-error";
function ResetAction({ story = "success", disabled = false, onComplete }: {
  story?: ResetStory; disabled?: boolean; onComplete?: () => void;
}) {
  const [feedback, setFeedback] = useState("");
  return <><LinearResetConnectionView disabled={disabled} onReset={async () => {
    await new Promise(resolve => window.setTimeout(resolve, 700));
    if (story === "partial-error") throw new Error("The channel could not be stopped. App settings were kept.");
    setFeedback("预览工作区及应用设置已清除。");
    onComplete?.();
  }} /><p role="status" className="mt-3 text-xs text-muted-foreground">{feedback}</p></>;
}

function ResetPreview() {
  const [story, setStory] = useState<ResetStory>("success");
  return <><StatePicker label="重置结果" value={story} options={["success", "partial-error"]} onChange={setStory} />
    <ResetAction key={story} story={story} /></>;
}

type PanelStory = "setup" | "configured" | "connected" | "missing-scopes" | "loading" | "inspection-error" | "save-error" | "runtime-error";
function panelFeature(story: PanelStory): NanobotFeatureInfo {
  const base = channelFeatures.linear;
  if (story === "setup") return base;
  return { ...base, configured: true, enabled: story === "connected" || story === "missing-scopes",
    runtime_status: story === "runtime-error" ? "failed" : story === "connected" || story === "missing-scopes" ? "running" : "stopped",
    runtime_error: story === "runtime-error" ? "Linear webhook could not be started." : undefined,
    configured_fields: ["channels.linear.clientId", "channels.linear.clientSecret", "channels.linear.webhookSigningSecret", "channels.linear.publicBaseUrl"],
    config_values: { ...base.config_values, "channels.linear.clientId": "gallery-linear-app", "channels.linear.publicBaseUrl": "https://nanobot.example" },
  };
}

function PanelComposition({ story }: { story: PanelStory }) {
  const { t, i18n } = useTranslation();
  const [feature, setFeature] = useState(() => panelFeature(story));
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const fields = setup.fields ?? [];
  const advancedFields = setup.manualFields ?? [];
  const [values, setValues] = useState(() => defaultChannelFieldValues([...fields, ...advancedFields], feature.config_values));
  const [configuredFields, setConfiguredFields] = useState(() => new Set(feature.configured_fields ?? []));
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [notice, setNotice] = useState<string | null>(story === "save-error" ? "Settings could not be saved. Your draft was kept." : null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [loading, setLoading] = useState(story === "loading");
  const [inspectionError, setInspectionError] = useState<string | null>(story === "inspection-error" ? "Connected workspaces could not be inspected." : null);
  const [installations, setInstallations] = useState<LinearInstallationSummary[]>(story === "connected" || story === "missing-scopes"
    ? [story === "missing-scopes" ? { ...workspace, authorization_status: "missing_scopes", missing_scopes: ["app:mentionable"] } : workspace] : []);
  const [connectStory, setConnectStory] = useState<ConnectStory>("idle");
  const [feedback, setFeedback] = useState("");
  const connecting = connectStory === "pending";
  const credentialsSaved = fields.filter(field => !field.optional).every(field =>
    configuredFields.has(field.key) || Boolean(feature.config_values?.[field.key]?.trim()));
  const save = async () => {
    if (story === "save-error") { setNotice("Settings could not be saved. Your draft was kept."); return false; }
    setFeature(current => ({ ...current, config_values: { ...current.config_values, ...values } }));
    setDirty(false); setSaved(true); setNotice(null); return true;
  };
  const connect = connection(connectStory);
  return <><LinearPanelView feature={feature} showBrandLogos={false} fields={fields} advancedFields={advancedFields}
    formProps={{ values, configuredFields, visibleSecrets, compact: true,
      disabled: connecting, onToggleSecret: (key) => setVisibleSecrets(current => ({ ...current, [key]: !current[key] })),
      onChange: (key, value) => { setValues(current => ({ ...current, [key]: value })); setDirty(true); setSaved(false); setNotice(null); },
      onFieldBlur: () => { void save(); },
    }}
    state={{ busy: false, dirty, saving: false, saved, connecting, credentialsSaved, connectionGeneration: 0, notice }}
    workspaces={{ installations: loading || inspectionError ? null : installations,
      logos: {}, loading, inspectionError,
      disconnectingId: null, notice: null, error: workspaceError }}
    onSave={save} onSaveSecret={async (key) => { setConfiguredFields(current => new Set(current).add(key)); setSaved(true); }}
    onRefreshWorkspaces={async () => { setLoading(false); setInspectionError(null); setFeedback("已刷新示例工作区。"); }}
    onDisconnectWorkspace={async (item, onRemoved) => {
      setInstallations(current => current.filter(entry => entry.organization_id !== item.organization_id));
      setFeature(current => ({ ...current, runtime_status: "stopped", enabled: false }));
      onRemoved(); setFeedback(`已移除示例工作区：${item.organization_name}`);
    }} onClearWorkspaceError={() => setWorkspaceError(null)} onRequestConnection={() => setConnectStory("pending")}
    onConfigureMcp={() => setFeedback("已选择 Linear MCP 配置入口。")}
    renderMemberAccess={(organizationId, disabled) => <MemberList key={organizationId} disabled={disabled} />}
    renderResetConnection={({ disabled, onComplete }) => <ResetAction disabled={disabled} onComplete={() => {
      setInstallations([]); setConfiguredFields(new Set()); setFeature(panelFeature("setup"));
      setValues(defaultChannelFieldValues([...fields, ...advancedFields])); onComplete();
    }} />}
    renderConnectFlow={(renderActions) => <LinearConnectFlowView connect={connect} busy={false} error={null}
      labels={linearConnectLabels(channelTranslator(t, "linear"))} connected={feature.runtime_status === "running" && installations.length > 0}
      suppressSucceeded={feature.runtime_status === "running" || feature.runtime_status === "failed"}
      renderActions={renderActions} onStart={() => setConnectStory("pending")} onCancel={() => setConnectStory("cancelled")}
      onPoll={async () => connect} />} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{feedback}</p></>;
}

function PanelPreview() {
  const [story, setStory] = useState<PanelStory>("connected");
  return <><StatePicker label="Linear 配置状态" value={story}
    options={["setup", "configured", "connected", "missing-scopes", "loading", "inspection-error", "save-error", "runtime-error"]}
    onChange={setStory} /><PanelComposition key={story} story={story} /></>;
}

export const linearChannelExamples: ComponentExample[] = [
  { title: "LinearPanelView · Linear 配置", files: ["nanobot/channels/linear/webui/LinearPanelView.tsx"], Preview: PanelPreview,
    description: "真实 Linear 配置面板：应用信息、密钥、高级设置、工作区菜单、成员权限及浏览器授权。",
    options: "state 与 workspaces 提供快照；工作区、保存与 MCP 操作由回调接入。三个插槽组合生产所用的成员、授权和重置视图。",
    code: "<LinearPanelView feature={feature} state={state} workspaces={workspaces} formProps={formProps} {...actions} {...composition} />" },
  { title: "LinearMemberAccessView · 成员访问", files: ["nanobot/channels/linear/webui/LinearMemberAccessView.tsx"], Preview: MembersPreview,
    description: "展开成员目录、搜索同名成员、修改权限；比较加载、刷新、空列表、保存和确认失败状态。",
    options: "snapshot 是已确认的成员状态。onLoad 与 onSetAllowed 交给频道入口；权限校验仍由网关负责。",
    code: "<LinearMemberAccessView snapshot={snapshot} onLoad={refresh} onSetAllowed={saveAccess} />" },
  { title: "LinearConnectFlowView · Linear 授权", files: ["nanobot/channels/linear/webui/LinearConnectFlowView.tsx"], Preview: AuthorizationPreview,
    description: "真实浏览器授权入口与等待提示，支持开始、取消、成功与失败阶段。",
    options: "复用 ChannelQrConnectFlowView，Linear 提供浏览器授权展示、标签与焦点处理。会话创建及轮询留在运行时入口。",
    code: "<LinearConnectFlowView connect={authorization} labels={labels} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />" },
  { title: "LinearResetConnectionView · 重置连接", files: ["nanobot/channels/linear/webui/LinearResetConnectionView.tsx"], Preview: ResetPreview,
    description: "打开重置确认，查看清除与保留范围、忙碌状态和部分完成后的重试提示。",
    options: "onReset 负责运行完整撤销与清理事务；视图管理确认、错误、关闭限制与焦点恢复。",
    code: "<LinearResetConnectionView disabled={false} onReset={resetConnection} />" },
];
