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
import { useGalleryTranslation } from "./i18n";

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
    error: story === "error" ? "previews.linearMembers.loadError" : null,
    saves: story === "saving" ? { "gallery-alex": { status: "saving" } }
      : story === "save-error" ? { "gallery-alex": { status: "error", message: "previews.linearMembers.saveError" } } : {},
  };
}

function MemberList({ story = "members", disabled = false }: { story?: MemberStory; disabled?: boolean }) {
  const { t } = useGalleryTranslation();
  const [snapshot, setSnapshot] = useState(() => memberSnapshot(story));
  return <LinearMemberAccessView snapshot={{ ...snapshot, error: snapshot.error ? t(snapshot.error) : null,
    saves: Object.fromEntries(Object.entries(snapshot.saves).map(([id, save]) => [id, save.status === "error" ? { ...save, message: t(save.message) } : save])),
  }} disabled={disabled}
    onLoad={(force) => { if (force) setSnapshot(memberSnapshot("members")); }}
    onSetAllowed={(id, allowed) => setSnapshot(current => ({ ...current,
      payload: current.payload ? { ...current.payload,
        members: current.payload.members.map(member => member.id === id ? { ...member, allowed } : member),
      } : null,
      saves: { ...current.saves, [id]: { status: "saved" } },
    }))} />;
}

function MembersPreview() {
  const { t } = useGalleryTranslation();
  const [story, setStory] = useState<MemberStory>("members");
  return <><StatePicker label={t("previews.linearMembers.state")} value={story}
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
  const { t: g } = useGalleryTranslation();
  const [story, setStory] = useState<ConnectStory>("idle");
  const connect = connection(story);
  return <><StatePicker label={g("previews.linearConnect.state")} value={story}
    options={["idle", "starting", "pending", "succeeded", "cancelled", "failed"]} onChange={setStory} />
    <LinearConnectFlowView connect={connect} busy={story === "starting"} error={story === "failed" ? g("previews.linearConnect.error") : null}
      labels={linearConnectLabels(channelTranslator(t, "linear"))}
      onStart={() => setStory("pending")} onCancel={() => setStory("cancelled")}
      onPoll={async () => connect} />
    <p className="mt-4 text-xs text-muted-foreground">{g("previews.linearConnect.hint")}</p></>;
}

type ResetStory = "success" | "partial-error";
function ResetAction({ story = "success", disabled = false, onComplete }: {
  story?: ResetStory; disabled?: boolean; onComplete?: () => void;
}) {
  const { t } = useGalleryTranslation();
  const [completed, setCompleted] = useState(false);
  return <><LinearResetConnectionView disabled={disabled} onReset={async () => {
    await new Promise(resolve => window.setTimeout(resolve, 700));
    if (story === "partial-error") throw new Error(t("previews.linearReset.error"));
    setCompleted(true);
    onComplete?.();
  }} /><p role="status" className="mt-3 text-xs text-muted-foreground">{completed ? t("previews.linearReset.completed") : ""}</p></>;
}

function ResetPreview() {
  const { t } = useGalleryTranslation();
  const [story, setStory] = useState<ResetStory>("success");
  return <><StatePicker label={t("previews.linearReset.state")} value={story} options={["success", "partial-error"]} onChange={setStory} />
    <ResetAction key={story} story={story} /></>;
}

type PanelStory = "setup" | "configured" | "connected" | "missing-scopes" | "loading" | "inspection-error" | "save-error" | "runtime-error";
function panelFeature(story: PanelStory): NanobotFeatureInfo {
  const base = channelFeatures.linear;
  if (story === "setup") return base;
  return { ...base, configured: true, enabled: story === "connected" || story === "missing-scopes",
    runtime_status: story === "runtime-error" ? "failed" : story === "connected" || story === "missing-scopes" ? "running" : "stopped",
    runtime_error: story === "runtime-error" ? "previews.linearPanel.runtimeError" : undefined,
    configured_fields: ["channels.linear.clientId", "channels.linear.clientSecret", "channels.linear.webhookSigningSecret", "channels.linear.publicBaseUrl"],
    config_values: { ...base.config_values, "channels.linear.clientId": "gallery-linear-app", "channels.linear.publicBaseUrl": "https://nanobot.example" },
  };
}

function PanelComposition({ story }: { story: PanelStory }) {
  const { t, i18n } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [feature, setFeature] = useState(() => panelFeature(story));
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const fields = setup.fields ?? [];
  const advancedFields = setup.manualFields ?? [];
  const [values, setValues] = useState(() => defaultChannelFieldValues([...fields, ...advancedFields], feature.config_values));
  const [configuredFields, setConfiguredFields] = useState(() => new Set(feature.configured_fields ?? []));
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [notice, setNotice] = useState<string | null>(story === "save-error" ? "previews.linearPanel.saveError" : null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [loading, setLoading] = useState(story === "loading");
  const [inspectionError, setInspectionError] = useState<string | null>(story === "inspection-error" ? "previews.linearPanel.inspectionError" : null);
  const [installations, setInstallations] = useState<LinearInstallationSummary[]>(story === "connected" || story === "missing-scopes"
    ? [story === "missing-scopes" ? { ...workspace, authorization_status: "missing_scopes", missing_scopes: ["app:mentionable"] } : workspace] : []);
  const [connectStory, setConnectStory] = useState<ConnectStory>("idle");
  const [feedback, setFeedback] = useState<{ key: string; name?: string } | null>(null);
  const connecting = connectStory === "pending";
  const credentialsSaved = fields.filter(field => !field.optional).every(field =>
    configuredFields.has(field.key) || Boolean(feature.config_values?.[field.key]?.trim()));
  const save = async () => {
    if (story === "save-error") { setNotice("previews.linearPanel.saveError"); return false; }
    setFeature(current => ({ ...current, config_values: { ...current.config_values, ...values } }));
    setDirty(false); setSaved(true); setNotice(null); return true;
  };
  const connect = connection(connectStory);
  return <><LinearPanelView feature={{ ...feature, runtime_error: feature.runtime_error ? g(feature.runtime_error) : undefined }} showBrandLogos={false} fields={fields} advancedFields={advancedFields}
    formProps={{ values, configuredFields, visibleSecrets, compact: true,
      disabled: connecting, onToggleSecret: (key) => setVisibleSecrets(current => ({ ...current, [key]: !current[key] })),
      onChange: (key, value) => { setValues(current => ({ ...current, [key]: value })); setDirty(true); setSaved(false); setNotice(null); },
      onFieldBlur: () => { void save(); },
    }}
    state={{ busy: false, dirty, saving: false, saved, connecting, credentialsSaved, connectionGeneration: 0, notice: notice ? g(notice) : null }}
    workspaces={{ installations: loading || inspectionError ? null : installations,
      logos: {}, loading, inspectionError: inspectionError ? g(inspectionError) : null,
      disconnectingId: null, notice: null, error: workspaceError }}
    onSave={save} onSaveSecret={async (key) => { setConfiguredFields(current => new Set(current).add(key)); setSaved(true); }}
    onRefreshWorkspaces={async () => { setLoading(false); setInspectionError(null); setFeedback({ key: "previews.linearPanel.refreshed" }); }}
    onDisconnectWorkspace={async (item, onRemoved) => {
      setInstallations(current => current.filter(entry => entry.organization_id !== item.organization_id));
      setFeature(current => ({ ...current, runtime_status: "stopped", enabled: false }));
      onRemoved(); setFeedback({ key: "previews.linearPanel.removed", name: item.organization_name });
    }} onClearWorkspaceError={() => setWorkspaceError(null)} onRequestConnection={() => setConnectStory("pending")}
    onConfigureMcp={() => setFeedback({ key: "previews.linearPanel.mcp" })}
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
    <p role="status" className="mt-4 text-xs text-muted-foreground">{feedback ? g(feedback.key, { name: feedback.name }) : ""}</p></>;
}

function PanelPreview() {
  const { t } = useGalleryTranslation();
  const [story, setStory] = useState<PanelStory>("connected");
  return <><StatePicker label={t("previews.linearPanel.state")} value={story}
    options={["setup", "configured", "connected", "missing-scopes", "loading", "inspection-error", "save-error", "runtime-error"]}
    onChange={setStory} /><PanelComposition key={story} story={story} /></>;
}

export const linearChannelExamples: ComponentExample[] = [
  { title: "previews.linearPanel.title", files: ["nanobot/channels/linear/webui/LinearPanelView.tsx"], Preview: PanelPreview,
    description: "previews.linearPanel.description",
    options: "previews.linearPanel.options",
    code: "<LinearPanelView feature={feature} state={state} workspaces={workspaces} formProps={formProps} {...actions} {...composition} />" },
  { title: "previews.linearMembers.title", files: ["nanobot/channels/linear/webui/LinearMemberAccessView.tsx"], Preview: MembersPreview,
    description: "previews.linearMembers.description",
    options: "previews.linearMembers.options",
    code: "<LinearMemberAccessView snapshot={snapshot} onLoad={refresh} onSetAllowed={saveAccess} />" },
  { title: "previews.linearConnect.title", files: ["nanobot/channels/linear/webui/LinearConnectFlowView.tsx"], Preview: AuthorizationPreview,
    description: "previews.linearConnect.description",
    options: "previews.linearConnect.options",
    code: "<LinearConnectFlowView connect={authorization} labels={labels} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />" },
  { title: "previews.linearReset.title", files: ["nanobot/channels/linear/webui/LinearResetConnectionView.tsx"], Preview: ResetPreview,
    description: "previews.linearReset.description",
    options: "previews.linearReset.options",
    code: "<LinearResetConnectionView disabled={false} onReset={resetConnection} />" },
];
