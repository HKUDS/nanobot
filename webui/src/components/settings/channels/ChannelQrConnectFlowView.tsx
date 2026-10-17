import { useEffect, useState, type ReactNode } from "react";
import QRCode from "qrcode";
import { Check, Loader2, RotateCcw } from "lucide-react";
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
  const displayMessage = connect
    ? resolveMessage?.(connect) ?? (connect.message ? channelValidationMessage(connect.message, t) : undefined)
    : undefined;

  useEffect(() => {
    if (!showQrCode || !connect?.qr_url) {
      setQrDataUrl("");
      return;
    }
    let cancelled = false;
    void QRCode.toDataURL(connect.qr_url, {
      width: 184,
      margin: 1,
      color: { dark: "#111827", light: "#ffffff" },
    })
      .then((url) => {
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
        <div role="status" className="grid min-h-[228px] place-items-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
          <span className="sr-only">{labels.connecting}</span>
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
        <div className={`grid gap-4 rounded-control border border-border/70 p-4 ${showQrCode ? "sm:grid-cols-[auto_minmax(0,1fr)]" : ""}`}>
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
            <div className="text-[13px] font-semibold text-foreground">
              {labels.scanTitle}
            </div>
            <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
              {!showQrCode || qrDataUrl ? labels.scanDescription : null}
            </p>
            {renderPending?.({ connect, busy, poll: onPoll }) ?? (
              <div className="mt-3 flex items-center gap-2 text-[12px] text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                {!showQrCode || qrDataUrl ? labels.waiting : labels.connecting}
              </div>
            )}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 rounded-full px-3 text-[12px] font-semibold"
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
        <div className="flex items-center gap-2 rounded-control border border-emerald-500/20 px-3 py-2 text-[12px] font-medium text-emerald-700 dark:text-emerald-200">
          <Check className="h-3.5 w-3.5" aria-hidden />
          {displayMessage ?? labels.connected}
        </div>
      ) : null}

      {connect && ["expired", "failed", "cancelled"].includes(connect.status)
        && !(connected && connect.status === "cancelled") ? (
        <div className="rounded-control border border-border/60 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
          {displayMessage || labels.stopped}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-control border border-destructive/20 px-3 py-2 text-[12px] leading-5 text-destructive">
          {error}
        </div>
      ) : null}

      {!pending && !(autoStart && busy && !connect) ? renderActionRow(
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold settings-hover"
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
