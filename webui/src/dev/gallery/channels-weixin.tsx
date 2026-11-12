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
import { useGalleryTranslation } from "./i18n";

const scan: ChannelConnectPayload = {
  session_id: "gallery-weixin",
  status: "pending",
  qr_url: "https://example.com/gallery/weixin-login",
};

type ConnectState = "starting" | "scan" | "verify" | "verify-error" | "connected"
  | "expired" | "failed" | "cancelled" | "error";

function WeixinConnectPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<ConnectState>("scan");
  const [notice, setNotice] = useState("");
  const connect: ChannelConnectPayload | WeixinVerificationPayload | null = mode === "starting" ? null
    : mode === "scan" || mode === "error" ? scan
      : mode === "verify" || mode === "verify-error" ? {
        ...scan, challenge: "verify_code", verification_failed: mode === "verify-error",
      } : { ...scan, status: mode === "connected" ? "succeeded" : mode };

  return <>
    <StatePicker label={t("previews.weixinConnect.state")} value={mode}
      options={["starting", "scan", "verify", "verify-error", "connected", "expired", "failed", "cancelled", "error"]}
      onChange={setMode} />
    <WeixinConnectFlowView connect={connect} busy={mode === "starting"} autoStart minimalPending
      error={mode === "error" ? t("previews.weixinConnect.error") : null}
      onStart={() => { setMode("scan"); setNotice("previews.weixinConnect.refreshed"); }}
      onCancel={() => setMode("cancelled")}
      onPoll={async (params) => {
        if (params?.verify_code === "123456") {
          setMode("connected");
          return { ...scan, status: "succeeded" };
        }
        setMode("verify-error");
        return { ...scan, challenge: "verify_code", verification_failed: true };
      }} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{t(notice || "previews.weixinConnect.hint")}</p>
  </>;
}

type PanelState = "unconfigured" | "running" | "auth-expired" | "saving" | "saved" | "save-error";

function WeixinPanelPreview() {
  const { t, i18n } = useTranslation();
  const { t: g } = useGalleryTranslation();
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
    <StatePicker label={g("previews.weixinPanel.state")} value={mode}
      options={["unconfigured", "running", "auth-expired", "saving", "saved", "save-error"]}
      onChange={(next) => { setMode(next); setEdited(false); }} />
    <WeixinPanelView feature={feature} actionKey={null} showBrandLogos={false}
      primaryFields={primaryFields} advancedFields={advancedFields} fieldValues={values}
      configuredFields={new Set()} secretVisibilityKey="gallery-weixin" runtimeError={runtimeError}
      saving={mode === "saving" && !edited} saveState={mode === "saved" || edited ? "saved" : "idle"}
      saveError={mode === "save-error" && !edited ? g("previews.linearPanel.saveError") : null}
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
  { title: "previews.weixinPanel.title", files: ["nanobot/channels/weixin/webui/WeixinPanelView.tsx"],
    Preview: WeixinPanelPreview, description: "previews.weixinPanel.description",
    options: "previews.weixinPanel.options",
    code: '<WeixinPanelView feature={feature} primaryFields={primary} advancedFields={advanced} fieldValues={values} saving={saving} saveState={saveState} saveError={error} connectFlow={connectFlow} onFieldChange={change} />' },
  { title: "previews.weixinConnect.title", files: ["nanobot/channels/weixin/webui/WeixinConnectFlowView.tsx"],
    Preview: WeixinConnectPreview, description: "previews.weixinConnect.description",
    options: "previews.weixinConnect.options",
    code: '<WeixinConnectFlowView connect={connect} busy={busy} error={error} autoStart minimalPending onStart={start} onCancel={cancel} onPoll={verify} />' },
];
