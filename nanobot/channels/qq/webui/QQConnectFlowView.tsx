import { useRef, useState } from "react";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelStatusBadge } from "@/components/settings/channels/ChannelIdentity";
import { ChannelQrConnectFlowView, type ChannelQrConnectFlowViewProps, type ChannelQrConnectLabels } from "@/components/settings/channels/ChannelQrConnectFlowView";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { ChannelRuntimeStatus } from "@/lib/types";

export type QQConnectFlowViewProps = Omit<ChannelQrConnectFlowViewProps, "labels"> & {
  configured?: boolean;
  appId?: string;
  runtimeStatus?: ChannelRuntimeStatus;
  runtimeLabel?: string;
  onManualSetup?: () => void;
};

export function useQQConnectLabels(): ChannelQrConnectLabels {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "qq");
  return {
    qrAlt: tx("custom.qrAlt", "QQ binding QR code"),
    scanTitle: tx("custom.scanTitle", "Scan with mobile QQ"),
    scanDescription: "",
    waiting: tx("custom.waiting", "Waiting for scan…"),
    connected: tx("custom.connected", "Binding complete"),
    stopped: tx("custom.stopped", "Cancelled"),
    connecting: tx("custom.connecting", "Preparing QR code…"),
    scanAgain: tx("custom.rebind", "Rebind bot"),
    connect: tx("custom.bind", "Bind QQ bot"),
  };
}

export function QQConnectFlowView({
  configured, appId, runtimeStatus, runtimeLabel, onManualSetup, ...props
}: QQConnectFlowViewProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "qq");
  const labels = useQQConnectLabels();
  const [rebindOpen, setRebindOpen] = useState(false);
  const rebindTrigger = useRef<HTMLElement | null>(null);
  const pending = props.connect?.status === "pending";
  const pollFailed = pending && props.errorAction === "poll" && Boolean(props.error);
  const retrying = props.connect?.retrying || pollFailed;
  const needsRetry = props.connect?.status === "failed" || Boolean(props.error);
  const idleLabel = needsRetry ? tx("custom.retry", "Retry")
    : props.connect?.status === "expired" ? tx("custom.refresh", "Refresh QR code")
      : configured ? labels.scanAgain : labels.connect;
  const manualSetup = onManualSetup ? (
    <Button type="button" size="sm" variant="link" className="px-0"
      disabled={props.busy} onClick={onManualSetup}>
      {tx("custom.manualSetup", "Enter credentials manually")}
    </Button>
  ) : null;

  return <div className="space-y-3">
    {configured ? (
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="flex items-center gap-2 text-ui-heading">
            <Check className="h-4 w-4 text-emerald-700 dark:text-emerald-200" aria-hidden />
            {tx("custom.configured", "Configured")}
          </p>
          {appId ? <p className="break-all text-caption text-muted-foreground">
            {tx("setup.fields.appId.label", "App ID")}: <code>{appId}</code>
          </p> : null}
        </div>
        {runtimeLabel ? <ChannelStatusBadge status={runtimeStatus}>{runtimeLabel}</ChannelStatusBadge> : null}
      </div>
    ) : null}
    <ChannelQrConnectFlowView {...props}
      onStart={() => {
        if (configured) {
          rebindTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          setRebindOpen(true);
        } else {
          props.onStart();
        }
      }}
      labels={{ ...labels, waiting: retrying
        ? tx("custom.retrying", "Retrying…") : labels.waiting }}
      idleLabel={idleLabel}
      error={pollFailed || !props.error ? null : props.errorAction === "cancel"
        ? tx("custom.cancelFailed", "Could not cancel") : tx("custom.failed", "Binding failed")}
      suppressSucceeded={configured}
      resolveMessage={(payload) => {
        switch (payload.status) {
          case "succeeded": return labels.connected;
          case "cancelled": return labels.stopped;
          case "expired": return tx("custom.expired", "QR code expired");
          case "failed": return tx("custom.failed", "Binding failed");
          default: return labels.waiting;
        }
      }}
      renderActions={(connectButton) => (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {manualSetup}
          <div className="ms-auto">{connectButton}</div>
        </div>
      )}
    />
    {pending || (props.autoStart && props.busy && !props.connect) ? manualSetup : null}
    <AlertDialog open={rebindOpen} onOpenChange={setRebindOpen}>
      <AlertDialogContent onCloseAutoFocus={(event) => {
        event.preventDefault();
        rebindTrigger.current?.focus();
      }}>
        <AlertDialogHeader>
          <AlertDialogTitle>{labels.scanAgain}</AlertDialogTitle>
          <AlertDialogDescription>
            {tx("custom.scanAgainWarning", "Rebinding may interrupt other apps using this QQ bot. If the App Secret is reset, the old secret becomes invalid and those apps need the new secret.")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("settings.actions.cancel", { defaultValue: "Cancel" })}</AlertDialogCancel>
          <AlertDialogAction onClick={props.onStart}>{labels.scanAgain}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;
}
