import { useCallback, useEffect, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { readPairReturn } from "@/lib/remote-pair-return";
import { needsRemoteSetup, readRemoteInstances, readSelectedRemote, readRecentRemotes, rememberSelectedRemote, rememberRecentRemote, remoteAction, validateRemoteConnection, type RemoteConnection, type RemoteDirectory, type SelectedRemote } from "@/lib/remote-instances";

// Never silently evict a view containing drafts or unfinished attachments.
// Tunnels are shared across browser tabs, so only explicit disconnect closes one.
export const MAX_HOST_VIEWS = 3;
export interface HostFrame {
  connection: RemoteConnection;
  loaded: boolean;
  offline: boolean;
  failures: number;
  healthCheck?: number;
  error?: string;
}
interface PendingSwitch { id: string; name: string }
interface SwitchFailure { id: string; code: string }

export function useHostSessions() {
  const { client, getToken } = useClient();
  const pageVisible = usePageVisibility();
  const [directory, setDirectory] = useState<RemoteDirectory | null>(null);
  const directoryRef = useRef(directory);
  const directoryRead = useRef<{ generation: number; ids: string[]; promise: Promise<RemoteDirectory> } | null>(null);
  const observers = useRef(0);
  const [observing, setObserving] = useState(false);
  const watchDirectory = useCallback(() => {
    observers.current += 1;
    setObserving(true);
    return () => { observers.current -= 1; setObserving(observers.current > 0); };
  }, []);
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
  // A notification may reveal its existing view, never reconnect a host.
  const reveal = useCallback((id: string) => {
    const frame = cache.current.get(id);
    if (!frame?.loaded || frame.offline) return false;
    cancel(); select(frame.connection);
    return true;
  }, [cancel, select]);
  const applyDirectory = useCallback((next: RemoteDirectory) => {
    directoryRef.current = next;
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
  const readDirectory = useCallback(function read(ids: string[] = [], wanted: () => boolean = () => true): Promise<RemoteDirectory> {
    if (!mounted.current || !wanted()) return Promise.resolve(directoryRef.current || { available: false, profiles: [] });
    if (window.top !== window) {
      const next = { available: false, profiles: [] };
      if (mounted.current) applyDirectory(next);
      return Promise.resolve(next);
    }
    // Visibility affects observation, never the shared transport's lifetime.
    if (document.visibilityState === "hidden") ids = [];
    const generation = directoryGeneration.current;
    const pendingRead = directoryRead.current;
    if (pendingRead?.generation === generation) {
      if (ids.every((id) => pendingRead.ids.includes(id))) return pendingRead.promise;
      return pendingRead.promise.catch(() => {}).then(() => read(ids, wanted));
    }
    const promise = readRemoteInstances(getToken(), ids).then((next) => {
      if (!mounted.current || generation !== directoryGeneration.current) return next;
      applyDirectory(next);
      for (const [id, frame] of cache.current) {
        if (id === pendingRef.current?.id) continue;
        const profile = next.profiles.find((item) => item.id === id);
        const changed = (!!profile?.gateway_id && profile.gateway_id !== frame.connection.gateway_id)
          || (!!profile?.view_id && profile.view_id !== frame.connection.view_id);
        const connected = !!profile?.connected && !changed;
        // Missing connections and changed identities are authoritative, not a
        // transient probe failure. A cached probe must not count twice.
        if (connected) frame.failures = 0;
        else if (!profile?.gateway_id || changed || needsRemoteSetup(profile.connection_error || "")) frame.failures = 2;
        else if (profile.health_check !== frame.healthCheck) frame.failures += 1;
        frame.healthCheck = profile?.health_check;
        if (connected || frame.failures >= 2) {
          frame.offline = !connected;
          frame.error = connected ? "" : changed ? "instance_changed" : profile?.connection_error || (!profile ? "profile_not_found" : "");
        }
        if (connected && frame.loaded) setFailure((current) => current?.id === id ? null : current);
      }
      if (cache.current.size) publish();
      return next;
    }).catch((reason: unknown) => {
      if (mounted.current && generation === directoryGeneration.current) {
        setDirectoryError(true);
        for (const id of ids) {
          const frame = cache.current.get(id);
          if (frame && id !== pendingRef.current?.id && ++frame.failures >= 2) {
            frame.offline = true; frame.error = "directory_unavailable";
          }
        }
        if (ids.length) publish();
      }
      throw reason;
    });
    directoryRead.current = { generation, ids, promise };
    const finish = () => { if (directoryRead.current?.promise === promise) directoryRead.current = null; };
    void promise.then(finish, finish);
    return promise;
  }, [applyDirectory, getToken, publish]);
  const healthTargets = useCallback(() => {
    const profiles = directoryRef.current?.profiles ?? [];
    const ids = observers.current ? profiles.filter((profile) => profile.gateway_id).map((profile) => profile.id) : [];
    if (selectedRef.current && cache.current.has(selectedRef.current.id)) ids.push(selectedRef.current.id);
    return [...new Set(ids)].filter((id) => id !== pendingRef.current?.id);
  }, []);
  const refresh = useCallback(async () => {
    const next = await readDirectory();
    const ids = healthTargets();
    return mounted.current && document.visibilityState !== "hidden" && ids.length ? readDirectory(ids) : next;
  }, [healthTargets, readDirectory]);

  const connect = useCallback(async (id: string, stillWanted: () => boolean = () => true) => {
    cancel();
    const attempt = epoch.current;
    const wanted = () => mounted.current && attempt === epoch.current && stillWanted();
    const warm = cache.current.get(id);
    if (!warm && cache.current.size >= MAX_HOST_VIEWS) {
      setFailure({ id, code: "view_limit" });
      throw new Error("view_limit");
    }
    directoryGeneration.current += 1;
    const name = directory?.profiles.find((item) => item.id === id)?.name || initial.current?.name || id;
    setPendingSwitch({ id, name });
    setFailure(null);
    let openingFrame = warm?.loaded ? undefined : warm;
    try {
      if (warm?.loaded && !warm.offline) {
        // A retained view may have spent hours unobserved. Check its identity
        // before reusing it, without reloading the iframe or reconnecting SSH.
        const next = await readDirectory([id], wanted);
        if (!wanted()) return;
        const profile = next.profiles.find((item) => item.id === id);
        if (profile?.connected && profile.gateway_id === warm.connection.gateway_id
          && profile.view_id === warm.connection.view_id) {
          select(warm.connection);
          return;
        }
        warm.offline = true;
        publish();
      }
      const connection = validateRemoteConnection(await remoteAction<RemoteConnection>(client, "connect", { id }));
      // Reads started before or during this mutation describe the old tunnel.
      directoryGeneration.current += 1;
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
      void readDirectory().catch(() => {});
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
  }, [cancel, client, directory, publish, readDirectory, refresh, select, setPendingSwitch]);
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
    void readDirectory().catch(() => {});
    return () => { mounted.current = false; directoryGeneration.current += 1; cancel(); };
  }, [cancel, readDirectory]);
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
    if (window.top !== window || !pageVisible || (!selected?.id && !observing)) return;
    let disposed = false;
    let running = false;
    let refreshPending = false;
    let timer: number | undefined;
    const hidden = () => document.visibilityState === "hidden";
    const poll = async (readList = false) => {
      if (disposed || hidden()) return;
      if (running) { refreshPending = true; return; }
      running = true;
      window.clearTimeout(timer);
      try {
        do {
          refreshPending = false;
          if (readList || (observing && !healthTargets().length)) await readDirectory([], () => !disposed && !hidden());
          if (disposed || hidden()) break;
          const ids = healthTargets();
          if (ids.length) await readDirectory(ids, () => !disposed && !hidden());
        } while (refreshPending && !disposed);
      } catch {
        // Keep the retained page; readDirectory owns health/error projection.
      } finally {
        running = false;
        if (refreshPending && !disposed && !hidden()) void poll(true);
        else if (!disposed && (healthTargets().length || observing)) timer = window.setTimeout(() => void poll(), 5_000);
      }
    };
    const wake = () => { void poll(true); };
    window.addEventListener("online", wake);
    window.addEventListener("pageshow", wake);
    void poll(true);
    return () => {
      disposed = true; window.clearTimeout(timer);
      window.removeEventListener("online", wake);
      window.removeEventListener("pageshow", wake);
    };
  }, [healthTargets, observing, pageVisible, pending?.id, readDirectory, selected?.id]);
  return { directory, directoryError, refresh, watchDirectory, rename, selected, recentIds, frames, pending,
    error: failure?.code || "", errorId: failure?.id, clearError, connect, cancel, local, reveal, disconnect, remove, loaded };
}
