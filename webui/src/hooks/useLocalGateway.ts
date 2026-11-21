import { useCallback, useEffect, useRef, useState } from "react";
import {
  BootstrapAuthRequiredError,
  clearSavedSecret,
  consumeUrlBootstrapSecret,
  deriveWsUrl,
  fetchBootstrap,
  loadSavedSecret,
  saveSecret,
} from "@/lib/bootstrap";
import { clearStoredComposerDrafts } from "@/lib/composer-draft";
import { NanobotClient } from "@/lib/nanobot-client";
import { activateReloadCache, clearReloadCache } from "@/lib/reload-cache";
import { createRuntimeHost, isNativeRuntime, toRuntimeSurface } from "@/lib/runtime";
import type { BootstrapResponse, RuntimeSurface } from "@/lib/types";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import { RESTART_ROUTE_KEY, RESTART_STARTED_KEY, rememberRestartRoute } from "@/shell-route";

type ReadyGateway = {
  status: "ready";
  client: NanobotClient;
  token: string;
  tokenExpiresAt: number | null;
  modelName: string | null;
  ingressLimits: BootstrapResponse["limits"] | null;
  runtimeSurface: RuntimeSurface;
  webuiCapabilities: string[];
};

type GatewayState = ReadyGateway | { status: "loading" } | { status: "auth" }
  | { status: "error"; message: string };

function bootstrapCredentials(boot: BootstrapResponse, fallbackSurface: RuntimeSurface) {
  const capabilities = boot.terminal?.webui?.capabilities;
  return {
    token: boot.api_token ?? "",
    tokenExpiresAt: boot.expires_in ? Date.now() + Math.max(0, boot.expires_in) * 1000 : null,
    runtimeSurface: isNativeRuntime(boot.runtime_surface) ? "native"
      : boot.runtime_surface ? toRuntimeSurface(boot.runtime_surface) : fallbackSurface,
    webuiCapabilities: Array.isArray(capabilities) ? capabilities.filter((entry) => typeof entry === "string") : [],
  };
}

function tokenRefreshDelayMs(expiresAt: number): number {
  const remaining = Math.max(0, expiresAt - Date.now());
  return Math.max(5_000, remaining - Math.min(30_000, Math.max(1_000, remaining / 2)));
}

function isBootstrapAuthRequired(error: unknown): boolean {
  if (error instanceof BootstrapAuthRequiredError) return true;
  const msg = error instanceof Error ? error.message : String(error);
  return msg.includes("HTTP 401") || msg.includes("HTTP 403");
}

function clearGatewayCaches() {
  clearReloadCache();
  clearStoredComposerDrafts();
  webuiThreadCache.clear();
}

/** Owns the local socket and credentials; remote panes have separate clients. */
export function useLocalGateway(prefetchChat: () => void) {
  const [state, setState] = useState<GatewayState>({ status: "loading" });
  const owner = useRef<NanobotClient | null>(null);
  const attempt = useRef(0);

  const closeClient = useCallback(() => {
    const client = owner.current;
    owner.current = null;
    client?.close();
  }, []);

  const refreshClient = useCallback(async (
    client: NanobotClient, secret: string, fallbackSurface: RuntimeSurface, signal?: AbortSignal,
  ) => {
    if (owner.current !== client) throw new DOMException("Gateway client changed", "AbortError");
    const boot = await fetchBootstrap("", secret);
    signal?.throwIfAborted();
    if (owner.current !== client) throw new DOMException("Gateway client changed", "AbortError");
    const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
    const credentials = bootstrapCredentials(boot, fallbackSurface);
    const host = createRuntimeHost(credentials.runtimeSurface, boot.runtime_capabilities);
    if (host.socketFactory) client.updateUrl(url, host.socketFactory);
    else client.updateUrl(url);
    client.updateMaxFrameBytes(boot.limits?.transport.max_frame_bytes);
    setState((current) => current.status === "ready" && current.client === client ? {
      ...current,
      ...credentials,
      modelName: boot.model_name ?? current.modelName,
      ingressLimits: boot.limits ?? current.ingressLimits,
    } : current);
    return { token: credentials.token, url };
  }, []);

  const secretRef = useRef("");
  const bootstrapWithSecret = useCallback((secret: string, onAuthRejected?: () => void) => {
    const generation = ++attempt.current;
    prefetchChat();
    if (!onAuthRejected) setState({ status: "loading" });
    void (async () => {
      try {
        const boot = await fetchBootstrap("", secret);
        if (generation !== attempt.current) return;
        if (secret) saveSecret(secret);
        const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
        activateReloadCache(url);
        const credentials = bootstrapCredentials(boot, "browser");
        const host = createRuntimeHost(credentials.runtimeSurface, boot.runtime_capabilities);
        const client: NanobotClient = new NanobotClient({
          url,
          maxFrameBytes: boot.limits?.transport.max_frame_bytes,
          socketFactory: host.socketFactory,
          onReauth: async (signal) => {
            try {
              return (await refreshClient(client, secret, credentials.runtimeSurface, signal)).url;
            } catch {
              return null;
            }
          },
        });
        secretRef.current = secret;
        owner.current = client;
        client.connect();
        setState({ status: "ready", client, ...credentials,
          modelName: boot.model_name ?? null, ingressLimits: boot.limits ?? null });
      } catch (error) {
        if (generation !== attempt.current) return;
        if (isBootstrapAuthRequired(error)) {
          clearGatewayCaches();
          if (onAuthRejected) onAuthRejected();
          else setState({ status: "auth" });
        } else {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    })();
  }, [prefetchChat, refreshClient]);

  useEffect(() => {
    bootstrapWithSecret(consumeUrlBootstrapSecret() || loadSavedSecret());
    return () => {
      ++attempt.current;
      closeClient();
    };
  }, [bootstrapWithSecret, closeClient]);

  const client = state.status === "ready" ? state.client : null;
  const expiresAt = state.status === "ready" ? state.tokenExpiresAt : null;
  const runtimeSurface = state.status === "ready" ? state.runtimeSurface : "browser";
  useEffect(() => {
    if (!client || expiresAt === null) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        await refreshClient(client, secretRef.current, runtimeSurface, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || owner.current !== client || !isBootstrapAuthRequired(error)) return;
        closeClient();
        clearGatewayCaches();
        setState({ status: "auth" });
      }
    }, tokenRefreshDelayMs(expiresAt));
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [client, closeClient, expiresAt, refreshClient, runtimeSurface]);

  const changeModelName = useCallback((modelName: string | null) => {
    setState((current) => current.status === "ready" ? { ...current, modelName } : current);
  }, []);

  const logout = useCallback(() => {
    ++attempt.current;
    closeClient();
    clearSavedSecret();
    clearGatewayCaches();
    setState({ status: "auth" });
  }, [closeClient]);

  const restartEngine = useCallback(async () => {
    const host = createRuntimeHost(runtimeSurface);
    if (!client || !host.restartEngine) throw new Error("native engine restart is unavailable");
    const secret = secretRef.current;
    rememberRestartRoute();
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    try {
      await host.restartEngine();
      return (await refreshClient(client, secret, runtimeSurface)).token;
    } finally {
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
        window.localStorage.removeItem(RESTART_ROUTE_KEY);
      } catch {
        // ignore storage errors
      }
    }
  }, [client, refreshClient, runtimeSurface]);

  return { state, bootstrapWithSecret, changeModelName, logout, restartEngine };
}
