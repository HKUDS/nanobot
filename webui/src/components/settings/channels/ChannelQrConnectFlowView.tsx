import { useEffect, useState, type ReactNode } from "react";
import { Check, CircleAlert, Clock, Loader2, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import type { ChannelConnectPayload } from "@/lib/types";
import { channelValidationMessage } from "./validationMessages";

export type ChannelQrConnectLabels = {
  qrAlt?: string;
  scanTitle: string;
  scanDescription: string;
  waiting: string;
  connected: string;
  stopped: string;
  connecting: string;
  scanAgain: string;
  connect: string;
};

export type ChannelQrConnectPendingContext = {
  connect: ChannelConnectPayload;
  busy: boolean;
  poll: (
    params?: Readonly<Record<string, string>>,
  ) => Promise<ChannelConnectPayload | null>;
};

export type ChannelQrConnectFlowViewProps = {
  connect: ChannelConnectPayload | null;
  busy: boolean;
  error: string | null;
  errorAction?: "start" | "poll" | "cancel";
  onStart: () => void;
  onCancel: () => void;
  onPoll: ChannelQrConnectPendingContext["poll"];
  idleLabel?: string;
  connected?: boolean;
  autoStart?: boolean;
  minimalPending?: boolean;
  showQrCode?: boolean;
  labels: ChannelQrConnectLabels;
  renderPending?: (context: ChannelQrConnectPendingContext) => ReactNode;
  resolveMessage?: (payload: ChannelConnectPayload) => string | undefined;
  suppressSucceeded?: boolean;
  renderActions?: (connectButton: ReactNode) => ReactNode;
};

export function ChannelQrConnectFlowView({
  connect,
  busy,
  error,
  onStart,
  onCancel,
  onPoll,
  idleLabel,
  connected = false,
  autoStart = false,
  minimalPending = false,
  showQrCode = true,
  labels,
  renderPending,
  resolveMessage,
  suppressSucceeded = false,
  renderActions,
}: ChannelQrConnectFlowViewProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [qrDataUrl, setQrDataUrl] = useState("");
  const pending = connect?.status === "pending";
  const succeeded = !pending && (connected || connect?.status === "succeeded");
  const canStart = !pending && !busy;
  const TerminalIcon = connect?.status === "expired" ? Clock : connect?.status === "failed" ? CircleAlert : X;
  const displayMessage = connect
    ? resolveMessage?.(connect) ?? (connect.message ? channelValidationMessage(connect.message, t) : undefined)
    : undefined;

  useEffect(() => {
    const qrUrl = connect?.qr_url;
    if (!showQrCode || !qrUrl) {
      setQrDataUrl("");
      return;
    }
    let cancelled = false;
    void import("qrcode")
      .then(async ({ default: QRCode }) => {
        if (cancelled) return;
        const url = await QRCode.toDataURL(qrUrl, {
          width: 184,
          margin: 1,
          color: { dark: "#111827", light: "#ffffff" },
        });
        if (!cancelled) setQrDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setQrDataUrl("");
      });
    return () => {
      cancelled = true;
    };
  }, [connect?.qr_url, showQrCode]);

  const renderActionRow = renderActions ?? ((connectButton: ReactNode) => (
    <div className="flex flex-wrap justify-end gap-2">{connectButton}</div>
  ));

  return (
    <div className="mt-3 space-y-3">
      {autoStart && busy && !connect ? (
        <div role="status" className="flex min-h-[228px] flex-col items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin motion-reduce:animate-none" aria-hidden />
          <span className="text-caption">{labels.connecting}</span>
        </div>
      ) : null}
      {pending && minimalPending && showQrCode ? (
        <div className="flex min-h-[228px] flex-col items-center justify-center gap-4 py-4">
          <div className="grid h-[196px] w-[196px] place-items-center rounded-control bg-background shadow-[inset_0_0_0_1px_oklch(0_0_0/0.1)] dark:shadow-[inset_0_0_0_1px_oklch(1_0_0/0.1)]">
            {qrDataUrl ? (
              <img
                src={qrDataUrl}
                alt={labels.qrAlt ?? labels.scanTitle}
                className="h-[184px] w-[184px]"
              />
            ) : (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
            )}
          </div>
          {renderPending?.({ connect, busy, poll: onPoll })}
        </div>
      ) : pending ? (
        <div className={`grid items-center gap-4 py-2 ${showQrCode ? "sm:grid-cols-[auto_minmax(0,1fr)]" : ""}`}>
          {showQrCode ? <div className="grid h-[196px] w-[196px] place-items-center rounded-control border border-border/60 bg-background">
            {qrDataUrl ? (
              <img
                src={qrDataUrl}
                alt={labels.qrAlt ?? labels.scanTitle}
                className="h-[184px] w-[184px]"
              />
            ) : (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
            )}
          </div> : null}
          <div className="flex min-w-0 flex-col justify-center">
            <div className="text-ui-heading text-foreground">
              {labels.scanTitle}
            </div>
            {labels.scanDescription && (!showQrCode || qrDataUrl) ? (
              <p className="mt-1 text-caption text-muted-foreground">{labels.scanDescription}</p>
            ) : null}
            {renderPending?.({ connect, busy, poll: onPoll }) ?? (
              <div role="status" className="mt-3 flex items-center gap-2 text-caption text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                {!showQrCode || qrDataUrl ? labels.waiting : labels.connecting}
              </div>
            )}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onCancel()}
                disabled={busy}
              >
                {tx("settings.actions.cancel", "Cancel")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {succeeded && !suppressSucceeded ? (
        <div role="status" className="flex items-center gap-2 text-caption text-emerald-700 dark:text-emerald-200">
          <Check className="h-3.5 w-3.5" aria-hidden />
          {displayMessage ?? labels.connected}
        </div>
      ) : null}

      {connect && ["expired", "failed", "cancelled"].includes(connect.status)
        && !(connected && connect.status === "cancelled") ? (
        <div role="status" className="flex items-center gap-2 text-caption text-muted-foreground">
          <TerminalIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {displayMessage || labels.stopped}
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="flex items-center gap-2 text-caption text-destructive">
          <CircleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {error}
        </div>
      ) : null}

      {!pending && !(autoStart && busy && !connect) ? renderActionRow(
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onStart()}
          disabled={!canStart}
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : succeeded ? (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          ) : null}
          {pending
            ? labels.connecting
            : succeeded
              ? labels.scanAgain
              : idleLabel ?? labels.connect}
        </Button>
      ) : null}
    </div>
  );
}
