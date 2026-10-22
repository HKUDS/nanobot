import { useCallback, useEffect, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { useStateRefresh } from "@/hooks/useStateRefresh";
import { readPairReturn } from "@/lib/remote-pair-return";
import { readRemoteInstances, readSelectedRemote, readRecentRemotes, rememberSelectedRemote, rememberRecentRemote, remoteAction, validateRemoteConnection, type RemoteConnection, type RemoteDirectory, type SelectedRemote } from "@/lib/remote-instances";

// Never silently evict a view containing drafts or unfinished attachments.
// Tunnels are shared across browser tabs, so only explicit disconnect closes one.
export const MAX_HOST_VIEWS = 3;
export interface HostFrame {
  connection: RemoteConnection;
  loaded: boolean;
  offline: boolean;
  failures: number;
  error?: string;
}
interface PendingSwitch { id: string; name: string }
interface SwitchFailure { id: string; code: string }

export function useHostSessions() {
  const { client, getToken, webuiCapabilities } = useClient();
  const stateEvents = webuiCapabilities.includes("webui.state-events.v1");
  const stateEventsRef = useRef(stateEvents);
  stateEventsRef.current = stateEvents;
  const [directory, setDirectory] = useState<RemoteDirectory | null>(null);
  const directoryRef = useRef(directory);
  directoryRef.current = directory;
  const [directoryError, setDirectoryError] = useState(false);
  const [selected, setSelected] = useState<SelectedRemote | null>(() => readPairReturn() ? null : readSelectedRemote());
  const [recentIds, setRecentIds] = useState(readRecentRemotes);
  const recentIdsRef = useRef(recentIds);
  const selectedRef = useRef(selected);
  const initial = useRef(selected);
  const cache = useRef(new Map<string, HostFrame>());
  const [frames, setFrames] = useState<HostFrame[]>([]);
  const [pending, setPending] = useState<PendingSwitch | null>(() => selected ? { id: selected.id, name: selected.name } : null);
  const pendingRef = useRef<PendingSwitch | null>(pending);
  const pendingHealth = useRef<RemoteDirectory | null>(null);
  const [failure, setFailure] = useState<SwitchFailure | null>(null);
  const clearError = useCallback(() => setFailure(null), []);
  const directoryGeneration = useRef(0);
  const directoryRead = useRef<Promise<RemoteDirectory> | null>(null);
  const queuedRead = useRef(false);
  const queuedHealth = useRef(false);
  const queuedSignal = useRef<AbortSignal>();
  const activeReadSignal = useRef<AbortSignal>();
  const directoryAbort = useRef<AbortController | null>(null);
  const followReadSignal = useRef<((signal?: AbortSignal) => void) | null>(null);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const waiter = useRef<{ id: string; finish: (ready: boolean) => void } | null>(null);
  const publish = useCallback(() => { if (mounted.current) setFrames([...cache.current.values()]); }, []);
  const applyFrameHealth = useCallback((frame: HostFrame, next: RemoteDirectory) => {
    const id = frame.connection.id;
    const profile = next.profiles.find((profile) => profile.id === id);
    const changed = (!!profile?.gateway_id && profile.gateway_id !== frame.connection.gateway_id)
      || (!!profile?.view_id && profile.view_id !== frame.connection.view_id);
    const connected = !!profile?.connected && !changed;
    // New hosts already debounce their shared transport samples. Waiting for
    // another browser read would strand this frame after the only invalidation.
    frame.failures = connected ? 0 : stateEventsRef.current ? 2 : frame.failures + 1;
    if (connected || frame.failures >= 2) {
      frame.offline = !connected;
      frame.error = connected ? "" : changed ? "instance_changed" : profile?.connection_error || (!profile ? "profile_not_found" : "");
    }
    if (connected && frame.loaded) setFailure((current) => current?.id === id ? null : current);
  }, []);
  const setPendingSwitch = useCallback((value: PendingSwitch | null) => {
    const previousId = pendingRef.current?.id;
    const health = pendingHealth.current;
    pendingRef.current = value;
    if (previousId !== value?.id) pendingHealth.current = null;
    if (!mounted.current) return;
    setPending(value);
    if (previousId && previousId !== value?.id && health) {
      const frame = cache.current.get(previousId);
      if (frame) { applyFrameHealth(frame, health); publish(); }
    }
  }, [applyFrameHealth, publish]);
  const cancel = useCallback(() => {
    epoch.current += 1;
    waiter.current?.finish(false);
    waiter.current = null;
    setPendingSwitch(null);
  }, [setPendingSwitch]);
  const select = useCallback((value: SelectedRemote | null) => {
    selectedRef.current = value;
    setSelected(value);
    rememberSelectedRemote(value);
    if (value) {
      recentIdsRef.current = rememberRecentRemote(value.id, recentIdsRef.current);
      setRecentIds(recentIdsRef.current);
    }
    setFailure(null);
    publish();
  }, [publish]);
  const local = useCallback(() => { cancel(); select(null); }, [cancel, select]);
  // A notification may reveal its existing view, never reconnect a host.
  const reveal = useCallback((id: string) => {
    const frame = cache.current.get(id);
    if (!frame?.loaded || frame.offline) return false;
    cancel(); select(frame.connection);
    return true;
  }, [cancel, select]);
  const applyDirectory = useCallback((next: RemoteDirectory) => {
    setDirectory(next); setDirectoryError(false);
    // Names are metadata, not a new host session. Keep iframe URLs, drafts,
    // selection and connection state intact when this or another tab renames.
    let changed = false;
    for (const profile of next.profiles) {
      const frame = cache.current.get(profile.id);
      if (frame && frame.connection.name !== profile.name) {
        frame.connection = { ...frame.connection, name: profile.name };
        changed = true;
      }
      if (selectedRef.current?.id === profile.id && selectedRef.current.name !== profile.name) {
        const value = { ...selectedRef.current, name: profile.name };
        selectedRef.current = value; setSelected(value); rememberSelectedRemote(value);
      }
      if (pendingRef.current?.id === profile.id && pendingRef.current.name !== profile.name) {
        setPendingSwitch({ id: profile.id, name: profile.name });
      }
    }
    if (changed) publish();
  }, [publish, setPendingSwitch]);
  const rename = useCallback(async (id: string, name: string) => {
    const next = await remoteAction<RemoteDirectory>(client, "rename", { id, name });
    // Discard health reads begun before the save completed.
    directoryGeneration.current += 1;
    if (mounted.current) applyDirectory(next);
  }, [applyDirectory, client]);
  const applyHealth = useCallback((next: RemoteDirectory) => {
    for (const [id, frame] of cache.current) {
      if (id === pendingRef.current?.id) { pendingHealth.current = next; continue; }
      applyFrameHealth(frame, next);
    }
    publish();
  }, [applyFrameHealth, publish]);
  const refresh = useCallback((signal = activeReadSignal.current, checkHealth = false): Promise<RemoteDirectory> => {
    if (document.visibilityState === "hidden") return Promise.resolve(directoryRef.current || { available: false, profiles: [] });
    if (directoryRead.current) {
      queuedRead.current = true;
      queuedHealth.current ||= checkHealth;
      queuedSignal.current = signal;
      followReadSignal.current?.(signal);
      return directoryRead.current;
    }
    const read = async () => {
      let next: RemoteDirectory = { available: false, profiles: [] };
      let error: unknown;
      do {
        queuedRead.current = false;
        queuedHealth.current = false;
        const generation = ++directoryGeneration.current;
        const controller = new AbortController();
        const linkedSignals = new Set<AbortSignal>();
        const abort = () => controller.abort();
        const follow = (source?: AbortSignal) => {
          if (!source) return;
          if (source.aborted) abort();
          else if (!linkedSignals.has(source)) {
            linkedSignals.add(source); source.addEventListener("abort", abort, { once: true });
          }
        };
        directoryAbort.current = controller;
        followReadSignal.current = follow;
        follow(signal);
        error = undefined;
        try {
          next = await (window.top === window ? readRemoteInstances(getToken(), controller.signal) : Promise.resolve({ available: false, profiles: [] }));
          if (mounted.current && !controller.signal.aborted && generation === directoryGeneration.current) {
            applyDirectory(next);
            if (stateEventsRef.current || checkHealth) applyHealth(next);
          }
        } catch (reason) {
          error = reason;
          if (mounted.current && !controller.signal.aborted && generation === directoryGeneration.current) {
            setDirectoryError(true);
            if (!stateEventsRef.current && checkHealth) {
              for (const [id, frame] of cache.current) {
                if (id === pendingRef.current?.id) continue;
                if (++frame.failures >= 2) { frame.offline = true; frame.error = "directory_unavailable"; }
              }
              publish();
            }
          }
        } finally {
          for (const source of linkedSignals) source.removeEventListener("abort", abort);
          followReadSignal.current = null;
          directoryAbort.current = null;
        }
        checkHealth = queuedHealth.current;
        signal = queuedSignal.current;
      } while (queuedRead.current && mounted.current && !signal?.aborted && document.visibilityState !== "hidden");
      directoryRead.current = null;
      if (error) throw error;
      return next;
    };
    const task = read();
    directoryRead.current = task;
    return task;
  }, [applyDirectory, applyHealth, getToken, publish]);

  const connect = useCallback(async (id: string, stillWanted: () => boolean = () => true) => {
    cancel();
    const attempt = epoch.current;
    const wanted = () => mounted.current && attempt === epoch.current && stillWanted();
    const warm = cache.current.get(id);
    if (warm?.loaded && !warm.offline) {
      if (wanted()) select(warm.connection);
      return;
    }
    if (!warm && cache.current.size >= MAX_HOST_VIEWS) {
      setFailure({ id, code: "view_limit" });
      throw new Error("view_limit");
    }
    // A health response started before this mutation describes the old tunnel.
    directoryGeneration.current += 1;
    const name = directory?.profiles.find((item) => item.id === id)?.name || initial.current?.name || id;
    setPendingSwitch({ id, name });
    setFailure(null);
    let openingFrame = warm?.loaded ? undefined : warm;
    try {
      const connection = validateRemoteConnection(await remoteAction<RemoteConnection>(client, "connect", { id }));
      if (!wanted()) {
        // A cancelled SSH request can finish later. Never switch away from the
        // latest choice or close its tunnel, which another tab may already use.
        return;
      }
      // Reads begun before connect completed still describe the previous tunnel.
      directoryGeneration.current += 1;
      pendingHealth.current = null;
      let frame = cache.current.get(id);
      if (!frame || frame.connection.url !== connection.url || frame.connection.gateway_id !== connection.gateway_id
        || frame.connection.view_id !== connection.view_id) {
        frame = { connection, loaded: false, offline: false, failures: 0 };
        cache.current.set(id, frame);
      } else {
        frame.connection = connection;
        frame.offline = false; frame.failures = 0; frame.error = "";
      }
      if (!frame.loaded) openingFrame = frame;
      publish();
      void refresh().catch(() => {});
      if (!frame.loaded) {
        const ready = await new Promise<boolean>((resolve, reject) => {
          const timer = window.setTimeout(() => {
            waiter.current = null;
            reject(new Error("view_load_failed"));
          // Cold remote bundles can take several SSH round trips. Keep the
          // current host usable and cancellable while giving them time to load.
          }, 60_000);
          waiter.current = { id, finish: (ready) => { window.clearTimeout(timer); resolve(ready); } };
        });
        if (!ready) return;
      }
      if (wanted()) select(frame.connection);
    } catch (reason) {
      if (wanted()) {
        setFailure({ id, code: reason instanceof Error ? reason.message : "unknown" });
        void refresh().catch(() => {});
        throw reason;
      }
    } finally {
      // Cancelled/failed cold pages contain no user work. Don't let them use up
      // the view budget; a newer attempt for this host owns its transport now.
      if (openingFrame && !openingFrame.loaded && cache.current.get(id) === openingFrame
        && (attempt === epoch.current || pendingRef.current?.id !== id)) {
        cache.current.delete(id);
        publish();
      }
      if (attempt === epoch.current) setPendingSwitch(null);
    }
  }, [cancel, client, directory, publish, refresh, select, setPendingSwitch]);
  const connectRef = useRef(connect);
  connectRef.current = connect;
  const loaded = useCallback((id: string) => {
    const frame = cache.current.get(id);
    if (frame) { frame.loaded = true; publish(); }
    if (waiter.current?.id === id) { waiter.current.finish(true); waiter.current = null; }
  }, [publish]);
  const closeConnection = useCallback(async (id: string, action: "disconnect" | "remove") => {
    directoryGeneration.current += 1;
    if (pendingRef.current?.id === id) cancel();
    // The backend owns the transaction. In particular, a failed Forget must
    // leave the connection and its browser view intact for a safe retry.
    const next = await remoteAction<RemoteDirectory>(client, action, { id });
    directoryGeneration.current += 1;
    if (!mounted.current) return;
    if (selectedRef.current?.id === id) local();
    cache.current.delete(id);
    applyDirectory(next);
    publish();
  }, [applyDirectory, cancel, client, local, publish]);
  const disconnect = useCallback((id: string) => closeConnection(id, "disconnect"), [closeConnection]);
  const remove = useCallback((id: string) => closeConnection(id, "remove"), [closeConnection]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; directoryGeneration.current += 1; directoryAbort.current?.abort(); cancel(); };
  }, [cancel]);
  useStateRefresh("remote_instances", window.top === window, async (signal, initial) => {
    activeReadSignal.current = signal;
    if (!stateEvents && !initial && !cache.current.size) return;
    await refresh(signal, !initial || cache.current.size > 0);
  }, 5_000);
  useEffect(() => {
    const wake = () => {
      if (document.visibilityState !== "hidden" && window.top === window) void refresh(undefined, true).catch(() => {});
    };
    window.addEventListener("online", wake);
    window.addEventListener("pageshow", wake);
    return () => {
      window.removeEventListener("online", wake);
      window.removeEventListener("pageshow", wake);
    };
  }, [refresh]);
  useEffect(() => {
    const saved = initial.current;
    if (!saved || window.top !== window) return;
    const restoration = epoch.current;
    let started = false;
    const timer = window.setTimeout(() => {
      started = true;
      if (selectedRef.current?.id === saved.id && epoch.current === restoration) {
        setPendingSwitch(null);
        setFailure({ id: saved.id, code: "ssh_unreachable" });
      }
    }, 15_000);
    const unsubscribe = client.onStatus((status) => {
      if (status !== "open" || started) return;
      started = true;
      window.clearTimeout(timer);
      if (selectedRef.current?.id !== saved.id || epoch.current !== restoration) return;
      void connectRef.current(saved.id).catch(() => {});
    });
    return () => { window.clearTimeout(timer); unsubscribe(); };
  }, [client, setPendingSwitch]);
  return { directory, directoryError, refresh, rename, selected, recentIds, frames, pending,
    error: failure?.code || "", errorId: failure?.id, clearError, connect, cancel, local, reveal, disconnect, remove, loaded };
}
