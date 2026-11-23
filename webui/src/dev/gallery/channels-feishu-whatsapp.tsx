import { useState } from "react";

import { FeishuAssistantsPanelView, type FeishuConnectOptions } from "../../../../nanobot/channels/feishu/webui/FeishuAssistantsPanelView";
import { FeishuConnectFlowView } from "../../../../nanobot/channels/feishu/webui/FeishuConnectFlowView";
import { WhatsAppConnectFlowView } from "../../../../nanobot/channels/whatsapp/webui/WhatsAppConnectFlowView";
import type { ChannelConnectPayload, NanobotChannelInstanceInfo } from "@/lib/types";
import { channelFeatures } from "./channel-fixtures";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

const connectStates = ["idle", "starting", "pending", "succeeded", "expired", "failed", "cancelled", "error"] as const;
type ConnectState = typeof connectStates[number];

function connectSnapshot(state: ConnectState): ChannelConnectPayload | null {
  if (state === "idle" || state === "starting" || state === "error") return null;
  return {
    session_id: "gallery-authorization",
    status: state,
    qr_url: "https://example.invalid/channel-authorization",
  };
}

function ConnectPreview({ channel }: { channel: "feishu" | "whatsapp" }) {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<ConnectState>("pending");
  const connect = connectSnapshot(state);
  const props = {
    connect,
    busy: state === "starting",
    error: state === "error" ? t("previews.channelConnect.error") : null,
    onStart: () => setState("pending"),
    onCancel: () => setState("cancelled"),
    onPoll: async () => connect,
  };
  return <>
    <StatePicker label={t("previews.channelConnect.state", { channel: channel === "feishu" ? "Feishu" : "WhatsApp" })} value={state} options={connectStates} onChange={setState} />
    {channel === "feishu"
      ? <FeishuConnectFlowView {...props} autoStart={state === "starting"} />
      : <WhatsAppConnectFlowView {...props} />}
  </>;
}

function FeishuConnectionPreview() {
  return <ConnectPreview channel="feishu" />;
}

function WhatsAppConnectionPreview() {
  return <ConnectPreview channel="whatsapp" />;
}

const assistantStates = ["running", "starting", "failed", "needs-authorization", "mixed"] as const;
type AssistantState = typeof assistantStates[number];

function assistantSnapshots(state: AssistantState): NanobotChannelInstanceInfo[] {
  const configured = state !== "needs-authorization";
  const first: NanobotChannelInstanceInfo = {
    id: "default",
    name: "nanobot",
    display_name: "Support assistant",
    enabled: configured,
    configured,
    runtime_status: state === "mixed" ? "running" : state === "needs-authorization" ? "stopped" : state,
    config_values: { ...channelFeatures.feishu.config_values, "channels.feishu.appId": "cli_gallery", "channels.feishu.domain": "feishu" },
    configured_fields: configured ? ["channels.feishu.appId", "channels.feishu.appSecret"] : [],
  };
  return state === "mixed" ? [first, {
    ...first,
    id: "product",
    display_name: "Product assistant",
    enabled: false,
    configured: false,
    runtime_status: "stopped",
    configured_fields: [],
  }] : [first];
}

function AssistantAuthorizationPreview({ idleLabel }: FeishuConnectOptions) {
  const [state, setState] = useState<ConnectState>("idle");
  const connect = connectSnapshot(state);
  return <FeishuConnectFlowView
    idleLabel={idleLabel}
    connect={connect}
    busy={false}
    error={null}
    onStart={() => setState("pending")}
    onCancel={() => setState("cancelled")}
    onPoll={async () => connect}
  />;
}

function FeishuAssistantsPreview() {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<AssistantState>("mixed");
  const [instances, setInstances] = useState(() => assistantSnapshots("mixed"));
  const [action, setAction] = useState<{ kind: "on" | "off"; name: string } | { kind: "saved"; name: string; amount: number } | null>(null);
  const feature = {
    ...channelFeatures.feishu,
    enabled: instances.some((instance) => instance.enabled),
    configured: instances.some((instance) => instance.configured),
    instances,
    runtime_error: state === "failed" ? t("previews.feishuAssistants.error") : undefined,
  };
  return <>
    <StatePicker label={t("previews.feishuAssistants.state")} value={state} options={assistantStates} onChange={(next) => {
      setState(next);
      setInstances(assistantSnapshots(next));
      setAction(null);
    }} />
    <FeishuAssistantsPanelView
      key={state}
      feature={feature}
      showBrandLogos={false}
      onToggleInstance={(instance, enabled) => {
        setInstances((current) => current.map((item) => item.id === instance.id ? {
          ...item, enabled, runtime_status: enabled ? "running" : "stopped",
        } : item));
        setAction({ kind: enabled ? "on" : "off", name: instance.display_name?.trim() || instance.name.trim() || instance.id });
      }}
      onSaveInstance={(instance, values) => {
        setInstances((current) => current.map((item) => item.id === instance.id ? {
          ...item, config_values: { ...item.config_values, ...values },
          configured_fields: [...new Set([...item.configured_fields, ...Object.keys(values)])],
        } : item));
        setAction({ kind: "saved", name: instance.display_name?.trim() || instance.name.trim() || instance.id, amount: Object.keys(values).length });
      }}
      renderConnectFlow={(options) => <AssistantAuthorizationPreview {...options} />}
    />
    {action ? <p role="status" className="mt-4 text-xs text-muted-foreground">{t(`previews.feishuAssistants.${action.kind}`, { name: action.name, amount: action.kind === "saved" ? action.amount : undefined })}</p> : null}
  </>;
}

export const feishuWhatsAppChannelExamples: ComponentExample[] = [
  {
    title: "previews.feishuConnect.title",
    files: ["nanobot/channels/feishu/webui/FeishuConnectFlowView.tsx", "webui/src/components/settings/channels/ChannelQrConnectFlowView.tsx"],
    description: "previews.feishuConnect.description",
    options: "previews.feishuConnect.options",
    code: "<FeishuConnectFlowView connect={connect} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />",
    Preview: FeishuConnectionPreview,
  },
  {
    title: "previews.feishuAssistants.title",
    files: ["nanobot/channels/feishu/webui/FeishuAssistantsPanelView.tsx", "webui/src/components/settings/channels/ChannelInstancesPanelView.tsx"],
    description: "previews.feishuAssistants.description",
    options: "previews.feishuAssistants.options",
    code: "<FeishuAssistantsPanelView feature={feature} showBrandLogos={false} onToggleInstance={toggle} onSaveInstance={save} renderConnectFlow={renderAuthorization} />",
    Preview: FeishuAssistantsPreview,
  },
  {
    title: "previews.whatsappConnect.title",
    files: ["nanobot/channels/whatsapp/webui/WhatsAppConnectFlowView.tsx"],
    description: "previews.whatsappConnect.description",
    options: "previews.whatsappConnect.options",
    code: "<WhatsAppConnectFlowView connect={connect} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />",
    Preview: WhatsAppConnectionPreview,
  },
];
