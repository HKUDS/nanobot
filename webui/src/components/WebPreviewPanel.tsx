import { useState } from "react";
import { useTranslation } from "react-i18next";

import { WebPreviewPanelView } from "@/components/WebPreviewPanelView";
import { isLoopbackHost } from "@/lib/network";
import { currentWebPreviewRestriction, parseWebLink } from "@/lib/web-preview";

interface WebPreviewPanelProps {
  url: string;
}

export function WebPreviewPanel({ url: value }: WebPreviewPanelProps) {
  const { t } = useTranslation();
  const [revision, setRevision] = useState(0);
  const url = parseWebLink(value);
  const restriction = currentWebPreviewRestriction(url);
  return <WebPreviewPanelView url={url} restriction={restriction} loopback={!!url && isLoopbackHost(url.hostname)}
    onRefresh={() => setRevision((n) => n + 1)}>
    {!restriction ? <iframe key={`${value}:${revision}`} title={t("webPreview.frame", { host: url!.host })}
      {...{ credentialless: "" }} sandbox="allow-scripts" referrerPolicy="no-referrer"
      allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'; payment 'none'; fullscreen 'none'; display-capture 'none'; usb 'none'; serial 'none'; hid 'none'"
      src={url!.href} className="min-h-0 w-full flex-1 border-0 bg-white" /> : null}
  </WebPreviewPanelView>;
}
