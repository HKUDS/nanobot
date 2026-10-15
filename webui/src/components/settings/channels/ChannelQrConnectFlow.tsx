import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

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

import {
  ChannelQrConnectFlowView,
  type ChannelQrConnectFlowViewProps,
  type ChannelQrConnectLabels,
  type ChannelQrConnectPendingContext,
} from "./ChannelQrConnectFlowView";

export type { ChannelQrConnectLabels, ChannelQrConnectPendingContext } from "./ChannelQrConnectFlowView";

export function ChannelQrConnectFlow({
  channelName,
  startParams = {},
  idleLabel,
  connectRequestId,
  forceOnRepeat = false,
  connected = false,
  autoStart = false,
  minimalPending = false,
  showQrCode = true,
  labels,
  onFeaturesUpdate,
  pausePolling,
  renderPending,
  resolveMessage,
  suppressSucceeded = false,
  onActiveChange,
  renderActions,
  renderView,
}: {
  token: string;
  channelName: string;
  startParams?: Readonly<Record<string, string | boolean>>;
  idleLabel?: string;
  connectRequestId?: number;
  forceOnRepeat?: boolean;
  connected?: boolean;
  autoStart?: boolean;
  minimalPending?: boolean;
  /** Browser-based authorization can reuse the flow without generating or showing a QR code. */
  showQrCode?: boolean;
  labels: ChannelQrConnectLabels;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  pausePolling?: (payload: ChannelConnectPayload) => boolean;
  renderPending?: (context: ChannelQrConnectPendingContext) => ReactNode;
  resolveMessage?: (payload: ChannelConnectPayload) => string | undefined;
  suppressSucceeded?: boolean;
  onActiveChange?: (active: boolean) => void;
  renderActions?: (connectButton: ReactNode) => ReactNode;
  renderView?: (props: ChannelQrConnectFlowViewProps) => ReactNode;
}) {
  const { client } = useClient();
  const pageVisible = usePageVisibility();
  const [connect, setConnect] = useState<ChannelConnectPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handledRequestId = useRef(0);
  const autoStarted = useRef(false);
  const pollInFlight = useRef(false);

  const pending = connect?.status === "pending";
  useEffect(() => {
    onActiveChange?.(pending || busy);
  }, [pending, busy, onActiveChange]);
  const pollingPaused = Boolean(connect && pausePolling?.(connect));
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
        ...startParams,
        ...(force ? { force: true } : {}),
      });
      setConnect(payload);
      if (payload.nanobot_features) {
        onFeaturesUpdate(payload.nanobot_features);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [channelName, client, startParams, onFeaturesUpdate]);

  useEffect(() => {
    const requested = Boolean(connectRequestId && connectRequestId !== handledRequestId.current);
    if (!requested && !(autoStart && !autoStarted.current)) return;
    handledRequestId.current = connectRequestId ?? 0;
    autoStarted.current = true;
    void start();
  }, [autoStart, connectRequestId, start]);

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

  const viewProps: ChannelQrConnectFlowViewProps = {
    connect,
    busy,
    error,
    onStart: () => void start(forceOnRepeat && !pending && (connected || connect?.status === "succeeded")),
    onCancel: () => void cancel(),
    onPoll: submitPoll,
    idleLabel,
    connected,
    autoStart,
    minimalPending,
    showQrCode,
    labels,
    renderPending,
    resolveMessage,
    suppressSucceeded,
    renderActions,
  };
  return renderView ? renderView(viewProps) : <ChannelQrConnectFlowView {...viewProps} />;
}
