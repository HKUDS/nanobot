import { useCallback, useEffect, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
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
  const { client, getToken } = useClient();
  const [directory, setDirectory] = useState<RemoteDirectory | null>(null);
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
  const [failure, setFailure] = useState<SwitchFailure | null>(null);
  const clearError = useCallback(() => setFailure(null), []);
  const directoryGeneration = useRef(0);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const waiter = useRef<{ id: string; finish: (ready: boolean) => void } | null>(null);
  const publish = useCallback(() => { if (mounted.current) setFrames([...cache.current.values()]); }, []);
  const setPendingSwitch = useCallback((value: PendingSwitch | null) => {
    pendingRef.current = value;
    if (mounted.current) setPending(value);
  }, []);
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
  const refresh = useCallback(async () => {
    const generation = ++directoryGeneration.current;
    try {
      const next = window.top === window ? await readRemoteInstances(getToken()) : { available: false, profiles: [] };
      if (mounted.current && generation === directoryGeneration.current) applyDirectory(next);
      return next;
    } catch (reason) {
      if (mounted.current && generation === directoryGeneration.current) setDirectoryError(true);
      throw reason;
    }
  }, [applyDirectory, getToken]);

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
    void refresh().catch(() => {});
    return () => { mounted.current = false; cancel(); };
  }, [cancel, refresh]);
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
  useEffect(() => {
    let checking = false;
    let cancelled = false;
    const tick = async () => {
      if (checking || !cache.current.size) return;
      checking = true;
      const generation = ++directoryGeneration.current;
      try {
        const next = await readRemoteInstances(getToken());
        if (cancelled || generation !== directoryGeneration.current) return;
        applyDirectory(next);
        for (const [id, frame] of cache.current) {
          if (id === pendingRef.current?.id) continue;
          const profile = next.profiles.find((profile) => profile.id === id);
          const changed = (!!profile?.gateway_id && profile.gateway_id !== frame.connection.gateway_id)
            || (!!profile?.view_id && profile.view_id !== frame.connection.view_id);
          const connected = !!profile?.connected && !changed;
          frame.failures = connected ? 0 : frame.failures + 1;
          if (connected || frame.failures >= 2) {
            frame.offline = !connected;
            frame.error = connected ? "" : changed ? "instance_changed" : profile?.connection_error || (!profile ? "profile_not_found" : "");
          }
          if (connected && frame.loaded) setFailure((current) => current?.id === id ? null : current);
        }
      } catch {
        if (!cancelled && generation === directoryGeneration.current) for (const [id, frame] of cache.current) {
          if (id === pendingRef.current?.id) continue;
          if (++frame.failures >= 2) { frame.offline = true; frame.error = "directory_unavailable"; }
        }
      } finally {
        checking = false;
        if (!cancelled) publish();
      }
    };
    const timer = window.setInterval(() => { void tick(); }, 5_000);
    // Background tabs throttle timers. Recheck promptly after waking or a
    // network change, without reloading a frame or changing the selected host.
    const wake = () => { if (document.visibilityState === "visible") void tick(); };
    window.addEventListener("online", wake);
    window.addEventListener("pageshow", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      cancelled = true; window.clearInterval(timer);
      window.removeEventListener("online", wake);
      window.removeEventListener("pageshow", wake);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [applyDirectory, client, getToken, publish]);
  return { directory, directoryError, refresh, rename, selected, recentIds, frames, pending,
    error: failure?.code || "", errorId: failure?.id, clearError, connect, cancel, local, disconnect, remove, loaded };
}
