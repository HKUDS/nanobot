import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import QRCode from "qrcode";
import { Check, Loader2, Network, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import {
  cancelChannelConnect,
  pollChannelConnect,
  startChannelConnect,
} from "@/lib/api";
import type {
  ChannelConnectPayload,
  NanobotFeaturesPayload,
} from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

export type ChannelQrConnectLabels = {
  qrAlt: string;
  scanTitle: string;
  scanDescription: string;
  waiting: string;
  connected: string;
  stopped: string;
  connecting: string;
  scanAgain: string;
  connect: string;
};

export type ChannelConnectStartOptions = {
  domain?: string;
  instanceId?: string;
  mode?: "replace" | "create";
  force?: boolean;
};

export type ChannelQrConnectPendingContext = {
  connect: ChannelConnectPayload;
  busy: boolean;
  poll: (
    params?: Readonly<Record<string, string>>,
  ) => Promise<ChannelConnectPayload | null>;
};

export function ChannelQrConnectFlow({
  channelName,
  startOptions = {},
  idleLabel,
  connectRequestId,
  forceOnRepeat = false,
  labels,
  onFeaturesUpdate,
  pausePolling,
  renderPending,
  resolveMessage,
  suppressSucceeded = false,
}: {
  token: string;
  channelName: string;
  startOptions?: ChannelConnectStartOptions;
  idleLabel?: string;
  connectRequestId?: number;
  forceOnRepeat?: boolean;
  labels: ChannelQrConnectLabels;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  pausePolling?: (payload: ChannelConnectPayload) => boolean;
  renderPending?: (context: ChannelQrConnectPendingContext) => ReactNode;
  resolveMessage?: (payload: ChannelConnectPayload) => string | undefined;
  suppressSucceeded?: boolean;
}) {
  const { client } = useClient();
  const pageVisible = usePageVisibility();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [connect, setConnect] = useState<ChannelConnectPayload | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [handledRequestId, setHandledRequestId] = useState(0);
  const pollInFlight = useRef(false);
  const startDomain = startOptions.domain;
  const startInstanceId = startOptions.instanceId;
  const startMode = startOptions.mode;
  const startForce = startOptions.force;

  const pending = connect?.status === "pending";
  const succeeded = connect?.status === "succeeded";
  const canStart = !pending && !busy;
  const pollingPaused = Boolean(connect && pausePolling?.(connect));
  const displayMessage = connect
    ? resolveMessage?.(connect) ?? connect.message
    : undefined;

  useEffect(() => {
    if (!connect?.qr_url) {
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
  }, [connect?.qr_url]);

  useEffect(() => {
    if (
      !connect?.session_id
      || connect.status !== "pending"
      || pollingPaused
      || !pageVisible
    ) return;
    let cancelled = false;
    const sessionId = connect.session_id;
    const poll = async () => {
      if (pollInFlight.current) return;
      pollInFlight.current = true;
      try {
        const payload = await pollChannelConnect(
          client,
          channelName,
          sessionId,
        );
        if (cancelled) return;
        setConnect((current) => ({
          ...(current ?? payload),
          ...payload,
          qr_url: payload.qr_url ?? current?.qr_url,
        }));
        if (payload.nanobot_features) {
          onFeaturesUpdate(payload.nanobot_features);
        }
        if (payload.status !== "pending") {
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        pollInFlight.current = false;
      }
    };
    const initial = window.setTimeout(() => void poll(), 900);
    const interval = window.setInterval(
      () => void poll(),
      Math.max(2500, connect.interval_ms ?? 5000),
    );
    return () => {
      cancelled = true;
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [
    channelName,
    client,
    connect?.interval_ms,
    connect?.session_id,
    connect?.status,
    onFeaturesUpdate,
    pageVisible,
    pollingPaused,
  ]);

  const start = useCallback(async (force = false) => {
    setBusy(true);
    setError(null);
    try {
      const payload = await startChannelConnect(client, channelName, {
        domain: startDomain,
        instanceId: startInstanceId,
        mode: startMode,
        force: force || startForce,
      });
      setConnect(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [channelName, client, startDomain, startForce, startInstanceId, startMode]);

  useEffect(() => {
    if (!connectRequestId || connectRequestId === handledRequestId) return;
    setHandledRequestId(connectRequestId);
    void start();
  }, [connectRequestId, handledRequestId, start]);

  const cancel = async () => {
    if (!connect?.session_id) {
      setConnect(null);
      return;
    }
    setBusy(true);
    try {
      const payload = await cancelChannelConnect(
        client,
        channelName,
        connect.session_id,
      );
      setConnect(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitPoll = async (
    params: Readonly<Record<string, string>> = {},
  ): Promise<ChannelConnectPayload | null> => {
    if (!connect?.session_id) return null;
    setBusy(true);
    setError(null);
    try {
      const payload = await pollChannelConnect(
        client,
        channelName,
        connect.session_id,
        params,
      );
      setConnect((current) => ({
        ...(current ?? payload),
        ...payload,
        qr_url: payload.qr_url ?? current?.qr_url,
      }));
      if (payload.nanobot_features) {
        onFeaturesUpdate(payload.nanobot_features);
      }
      if (payload.status !== "pending") {
        setError(null);
      }
      return payload;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      {pending ? (
        <div className="grid gap-4 rounded-[14px] border border-border/70 p-4 sm:grid-cols-[auto_minmax(0,1fr)]">
          <div className="grid h-[196px] w-[196px] place-items-center rounded-[14px] border border-border/60 bg-background">
            {qrDataUrl ? (
              <img
                src={qrDataUrl}
                alt={labels.qrAlt}
                className="h-[184px] w-[184px]"
              />
            ) : (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
            )}
          </div>
          <div className="flex min-w-0 flex-col justify-center">
            <div className="text-[13px] font-semibold text-foreground">
              {labels.scanTitle}
            </div>
            <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
              {labels.scanDescription}
            </p>
            {renderPending?.({ connect, busy, poll: submitPoll }) ?? (
              <div className="mt-3 flex items-center gap-2 text-[12px] text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                {labels.waiting}
              </div>
            )}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 rounded-full px-3 text-[12px] font-semibold"
                onClick={() => void cancel()}
                disabled={busy}
              >
                {tx("settings.actions.cancel", "Cancel")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {succeeded && !suppressSucceeded ? (
        <div className="flex items-center gap-2 rounded-[12px] border border-emerald-500/20 px-3 py-2 text-[12px] font-medium text-emerald-700 dark:text-emerald-200">
          <Check className="h-3.5 w-3.5" aria-hidden />
          {displayMessage ?? labels.connected}
        </div>
      ) : null}

      {connect && ["expired", "failed", "cancelled"].includes(connect.status) ? (
        <div className="rounded-[12px] border border-border/60 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
          {displayMessage || labels.stopped}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-[12px] border border-destructive/20 px-3 py-2 text-[12px] leading-5 text-destructive">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
          onClick={() => void start(forceOnRepeat && succeeded)}
          disabled={!canStart}
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : succeeded ? (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          ) : (
            <Network className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {pending
            ? labels.connecting
            : succeeded
              ? labels.scanAgain
              : idleLabel ?? labels.connect}
        </Button>
      </div>
    </div>
  );
}
