import { useState } from "react";

import { QQConnectFlowView } from "../../../../nanobot/channels/qq/webui/QQConnectFlowView";
import type { ChannelConnectPayload } from "@/lib/types";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

const connectStates = ["idle", "starting", "pending", "retrying", "succeeded", "expired", "failed", "cancelled", "error"] as const;
type ConnectState = typeof connectStates[number];

function QQConnectionPreview() {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<ConnectState>("pending");
  const connect: ChannelConnectPayload | null = state === "idle" || state === "starting" || state === "error"
    ? null
    : { session_id: "gallery-qq", status: state === "retrying" ? "pending" : state,
      retrying: state === "retrying", qr_url: "https://example.invalid/qq-authorization" };
  return <>
    <StatePicker label={t("previews.channelConnect.state", { channel: "QQ" })} value={state} options={connectStates} onChange={setState} />
    <QQConnectFlowView connect={connect} busy={state === "starting"} autoStart={state === "starting"}
      configured={state === "succeeded"}
      error={state === "error" ? t("previews.channelConnect.error") : null}
      onStart={() => setState("pending")} onCancel={() => setState("cancelled")} onPoll={async () => connect} />
  </>;
}

export const qqChannelExamples: ComponentExample[] = [{
  title: "previews.qqConnect.title",
  files: ["nanobot/channels/qq/webui/index.tsx", "nanobot/channels/qq/webui/QQConnectFlowView.tsx"],
  description: "previews.qqConnect.description",
  options: "previews.qqConnect.options",
  code: "<QQConnectFlowView connect={connect} busy={busy} error={error} configured={configured} onStart={start} onCancel={cancel} onPoll={poll} />",
  Preview: QQConnectionPreview,
}];
