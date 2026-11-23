import { useCallback, useRef } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelQrConnectFlowView, type ChannelQrConnectFlowViewProps, type ChannelQrConnectLabels } from "@/components/settings/channels/ChannelQrConnectFlowView";
import { Button } from "@/components/ui/button";

export function linearConnectLabels(tx: ReturnType<typeof channelTranslator>): ChannelQrConnectLabels {
  return {
    scanTitle: tx("custom.authorizeTitle", "Authorize in Linear"),
    scanDescription: tx("custom.authorizeDescription", "Continue in Linear to choose a workspace and authorize nanobot. Return here when you're done."),
    waiting: tx("custom.waiting", "Waiting for Linear authorization..."),
    connected: tx("custom.connected", "Linear is connected."),
    stopped: tx("custom.stopped", "Authorization stopped."),
    connecting: tx("custom.connecting", "Connecting..."),
    scanAgain: tx("custom.reauthorize", "Reauthorize"),
    connect: tx("custom.connect", "Connect Linear"),
  };
}

export function LinearConnectFlowView(props: ChannelQrConnectFlowViewProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const flowRef = useRef<HTMLDivElement | null>(null);
  const revealAuthorization = useCallback((link: HTMLAnchorElement | null) => {
    if (!link) return;
    flowRef.current?.scrollIntoView({ block: "nearest" });
    link.focus({ preventScroll: true });
  }, []);

  return (
    <div ref={flowRef} className="mt-3 space-y-3">
      <ChannelQrConnectFlowView {...props} showQrCode={false}
        renderPending={({ connect }) => (
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <span className="h-2 w-2 animate-pulse rounded-full bg-[#5E6AD2] motion-reduce:animate-none" aria-hidden />
              {tx("custom.waiting", "Waiting for Linear authorization...")}
            </div>
            {connect.qr_url ? (
              <Button
                asChild
                size="sm"
                className="h-8 rounded-full px-3 text-[12px] font-semibold"
              >
                <a ref={revealAuthorization} href={connect.qr_url} target="_blank" rel="noreferrer">
                  <ExternalLink className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                  {tx("custom.openLinear", "Continue in Linear")}
                </a>
              </Button>
            ) : null}
          </div>
        )}
      />
    </div>
  );
}
