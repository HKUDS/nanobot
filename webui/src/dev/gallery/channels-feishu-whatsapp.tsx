import { useState } from "react";

import { FeishuAssistantsPanelView, type FeishuConnectOptions } from "../../../../nanobot/channels/feishu/webui/FeishuAssistantsPanelView";
import { FeishuConnectFlowView } from "../../../../nanobot/channels/feishu/webui/FeishuConnectFlowView";
import { WhatsAppConnectFlowView } from "../../../../nanobot/channels/whatsapp/webui/WhatsAppConnectFlowView";
import type { ChannelConnectPayload, NanobotChannelInstanceInfo } from "@/lib/types";
import { channelFeatures } from "./channel-fixtures";
import { StatePicker, type ComponentExample } from "./example";

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
  const [state, setState] = useState<ConnectState>("pending");
  const connect = connectSnapshot(state);
  const props = {
    connect,
    busy: state === "starting",
    error: state === "error" ? "Authorization is temporarily unavailable. Try again." : null,
    onStart: () => setState("pending"),
    onCancel: () => setState("cancelled"),
    onPoll: async () => connect,
  };
  return <>
    <StatePicker label={`${channel === "feishu" ? "Feishu" : "WhatsApp"} 连接状态`} value={state} options={connectStates} onChange={setState} />
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
  const [state, setState] = useState<AssistantState>("mixed");
  const [instances, setInstances] = useState(() => assistantSnapshots("mixed"));
  const [action, setAction] = useState("");
  const feature = {
    ...channelFeatures.feishu,
    enabled: instances.some((instance) => instance.enabled),
    configured: instances.some((instance) => instance.configured),
    instances,
    runtime_error: state === "failed" ? "The assistant stopped. Check its credentials before restarting." : undefined,
  };
  return <>
    <StatePicker label="助手运行状态" value={state} options={assistantStates} onChange={(next) => {
      setState(next);
      setInstances(assistantSnapshots(next));
      setAction("");
    }} />
    <FeishuAssistantsPanelView
      key={state}
      feature={feature}
      showBrandLogos={false}
      onToggleInstance={(instance, enabled) => {
        setInstances((current) => current.map((item) => item.id === instance.id ? {
          ...item, enabled, runtime_status: enabled ? "running" : "stopped",
        } : item));
        setAction(`${instance.display_name}: ${enabled ? "On" : "Off"}`);
      }}
      onSaveInstance={(instance, values) => {
        setInstances((current) => current.map((item) => item.id === instance.id ? {
          ...item, config_values: { ...item.config_values, ...values },
          configured_fields: [...new Set([...item.configured_fields, ...Object.keys(values)])],
        } : item));
        setAction(`${instance.display_name}: saved ${Object.keys(values).length} preview fields`);
      }}
      renderConnectFlow={(options) => <AssistantAuthorizationPreview {...options} />}
    />
    {action ? <p role="status" className="mt-4 text-xs text-muted-foreground">{action}</p> : null}
  </>;
}

export const feishuWhatsAppChannelExamples: ComponentExample[] = [
  {
    title: "FeishuConnectFlowView · 飞书扫码授权",
    files: ["nanobot/channels/feishu/webui/FeishuConnectFlowView.tsx", "webui/src/components/settings/channels/ChannelQrConnectFlowView.tsx"],
    description: "查看飞书真实扫码界面，切换等待、授权成功、到期、取消与错误，体验取消和重新扫码。",
    options: "connect、busy 和 error 是已有显示状态；视图本地生成二维码。开始、取消与轮询由功能入口提供，预览回调只改变当前示例。",
    code: "<FeishuConnectFlowView connect={connect} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />",
    Preview: FeishuConnectionPreview,
  },
  {
    title: "FeishuAssistantsPanelView · 飞书助手管理",
    files: ["nanobot/channels/feishu/webui/FeishuAssistantsPanelView.tsx", "webui/src/components/settings/channels/ChannelInstancesPanelView.tsx"],
    description: "展示多个真实助手卡片、运行与授权状态，试用开关、高级设置、保存和添加另一个助手。",
    options: "feature 和 instances 提供助手快照；视图管理字段草稿与保存反馈。onToggleInstance、onSaveInstance 与 renderConnectFlow 由所属功能接入运行时操作。",
    code: "<FeishuAssistantsPanelView feature={feature} showBrandLogos={false} onToggleInstance={toggle} onSaveInstance={save} renderConnectFlow={renderAuthorization} />",
    Preview: FeishuAssistantsPreview,
  },
  {
    title: "WhatsAppConnectFlowView · WhatsApp 设备关联",
    files: ["nanobot/channels/whatsapp/webui/WhatsAppConnectFlowView.tsx"],
    description: "使用正式 WhatsApp 极简二维码布局，比较自动连接、关联成功、到期和错误提示，并试用关联另一个账号。",
    options: "此视图沿用自动开始和极简布局的显示规则；调用方控制状态和重试。真实自动开始、强制重试和轮询仍由连接功能入口负责。",
    code: "<WhatsAppConnectFlowView connect={connect} busy={busy} error={error} onStart={start} onCancel={cancel} onPoll={poll} />",
    Preview: WhatsAppConnectionPreview,
  },
];
