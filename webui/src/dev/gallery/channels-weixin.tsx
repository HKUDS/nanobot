import { useState } from "react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { defaultChannelFieldValues } from "@/components/settings/channels/CredentialForm";
import type { ChannelConnectPayload } from "@/lib/types";
import { WeixinPanelView } from "../../../../nanobot/channels/weixin/webui/WeixinPanelView";
import { WeixinConnectFlowView } from "../../../../nanobot/channels/weixin/webui/WeixinConnectFlowView";
import {
  localizeBooleanFields,
  WEIXIN_AUTH_EXPIRED_MESSAGE,
  weixinSetupFields,
  type WeixinVerificationPayload,
} from "../../../../nanobot/channels/weixin/webui/presentation";

import { channelFeatures } from "./channel-fixtures";
import { StatePicker, type ComponentExample } from "./example";

const scan: ChannelConnectPayload = {
  session_id: "gallery-weixin",
  status: "pending",
  qr_url: "https://example.com/gallery/weixin-login",
};

type ConnectState = "starting" | "scan" | "verify" | "verify-error" | "connected"
  | "expired" | "failed" | "cancelled" | "error";

function WeixinConnectPreview() {
  const [mode, setMode] = useState<ConnectState>("scan");
  const [notice, setNotice] = useState("");
  const connect: ChannelConnectPayload | WeixinVerificationPayload | null = mode === "starting" ? null
    : mode === "scan" || mode === "error" ? scan
      : mode === "verify" || mode === "verify-error" ? {
        ...scan, challenge: "verify_code", verification_failed: mode === "verify-error",
      } : { ...scan, status: mode === "connected" ? "succeeded" : mode };

  return <>
    <StatePicker label="微信连接状态" value={mode}
      options={["starting", "scan", "verify", "verify-error", "connected", "expired", "failed", "cancelled", "error"]}
      onChange={setMode} />
    <WeixinConnectFlowView connect={connect} busy={mode === "starting"} autoStart minimalPending
      error={mode === "error" ? "Connection interrupted. Try again." : null}
      onStart={() => { setMode("scan"); setNotice("已显示新的预览二维码。"); }}
      onCancel={() => setMode("cancelled")}
      onPoll={async (params) => {
        if (params?.verify_code === "123456") {
          setMode("connected");
          return { ...scan, status: "succeeded" };
        }
        setMode("verify-error");
        return { ...scan, challenge: "verify_code", verification_failed: true };
      }} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{notice || "验证码预览输入 123456 可完成连接；其他输入会保留草稿并显示错误。"}</p>
  </>;
}

type PanelState = "unconfigured" | "running" | "auth-expired" | "saving" | "saved" | "save-error";

function WeixinPanelPreview() {
  const { t, i18n } = useTranslation();
  const channelTx = channelTranslator(t, "weixin");
  const [mode, setMode] = useState<PanelState>("running");
  const [edited, setEdited] = useState(false);
  const feature = {
    ...channelFeatures.weixin,
    configured: mode !== "unconfigured",
    enabled: mode !== "unconfigured",
    runtime_status: mode === "auth-expired" ? "failed" : mode === "unconfigured" ? "stopped" : "running",
    runtime_error: mode === "auth-expired" ? WEIXIN_AUTH_EXPIRED_MESSAGE : undefined,
  };
  const setup = weixinSetupFields(feature, i18n.resolvedLanguage ?? i18n.language);
  const onLabel = t("settings.values.on", { defaultValue: "On" });
  const offLabel = t("settings.values.off", { defaultValue: "Off" });
  const primaryFields = localizeBooleanFields(setup.primary, onLabel, offLabel);
  const advancedFields = localizeBooleanFields(setup.advanced, onLabel, offLabel);
  const [values, setValues] = useState(() => defaultChannelFieldValues([...primaryFields, ...advancedFields], {
    "channels.weixin.allowFrom": "preview-user",
  }));
  const [connect, setConnect] = useState<ChannelConnectPayload>(scan);
  const runtimeError = mode === "auth-expired" ? channelTx("custom.expired", WEIXIN_AUTH_EXPIRED_MESSAGE) : undefined;

  return <>
    <StatePicker label="微信面板状态" value={mode}
      options={["unconfigured", "running", "auth-expired", "saving", "saved", "save-error"]}
      onChange={(next) => { setMode(next); setEdited(false); }} />
    <WeixinPanelView feature={feature} actionKey={null} showBrandLogos={false}
      primaryFields={primaryFields} advancedFields={advancedFields} fieldValues={values}
      configuredFields={new Set()} secretVisibilityKey="gallery-weixin" runtimeError={runtimeError}
      saving={mode === "saving" && !edited} saveState={mode === "saved" || edited ? "saved" : "idle"}
      saveError={mode === "save-error" && !edited ? "Unable to save settings. Your draft is preserved." : null}
      connectFlow={mode === "unconfigured" || mode === "auth-expired" ? <WeixinConnectFlowView
        connect={connect} busy={false} error={null} autoStart minimalPending
        suppressSucceeded={mode === "auth-expired"}
        onStart={() => setConnect(scan)} onCancel={() => setConnect({ ...scan, status: "cancelled" })}
        onPoll={async () => connect} /> : null}
      onInstall={() => {}}
      onFieldChange={(key, value) => { setValues((current) => ({ ...current, [key]: value })); setEdited(true); }} />
  </>;
}

export const weixinChannelExamples: ComponentExample[] = [
  { title: "WeixinPanelView · 微信设置", files: ["nanobot/channels/weixin/webui/WeixinPanelView.tsx"],
    Preview: WeixinPanelPreview, description: "查看微信设置、高级参数、保存反馈和登录过期恢复。",
    options: "字段来自频道的真实设置契约。视图管理展开和密钥可见状态；运行时入口负责自动保存、草稿合并和登录恢复。",
    code: '<WeixinPanelView feature={feature} primaryFields={primary} advancedFields={advanced} fieldValues={values} saving={saving} saveState={saveState} saveError={error} connectFlow={connectFlow} onFieldChange={change} />' },
  { title: "WeixinConnectFlowView · 微信扫码与验证", files: ["nanobot/channels/weixin/webui/WeixinConnectFlowView.tsx"],
    Preview: WeixinConnectPreview, description: "比较扫码、验证码、成功、过期、取消和连接错误。",
    options: "视图接收连接快照与操作回调，并保留验证码草稿。二维码生成在浏览器中进行；授权启动、轮询暂停、刷新和取消由真实入口负责。",
    code: '<WeixinConnectFlowView connect={connect} busy={busy} error={error} autoStart minimalPending onStart={start} onCancel={cancel} onPoll={verify} />' },
];
