import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";

import { checkVersion, changeUpdateChannel, type ReleaseStatus, type UpdateChannel, type UpdateMethod, type WebUIMutationTransport } from "@/lib/api";

export type VersionResult =
  | { type: "up-to-date" }
  | { type: "update"; latestVersion: string; pypiUrl?: string; releaseUrl?: string }
  | { type: "release-status"; state: ReleaseStatus["state"] }
  | { type: "error"; message: string }
  | null;

interface VersionCheckState {
  installationMethod: UpdateMethod | null;
  result: VersionResult;
  checking: boolean;
  dismissedVersion: string | null;
  check: () => Promise<void>;
  dismiss: () => void;
  releaseStatus: ReleaseStatus | null;
  canChangeChannel: boolean;
  changingChannel: boolean;
  channelError: string;
  changeChannel: (channel: UpdateChannel) => Promise<void>;
}

const VersionCheckContext = createContext<VersionCheckState | null>(null);

// Per-connection store: old responses can only update their original store.
// Changing credentials must not remount the application or discard chat drafts.
function createVersionCheck(token: string, channels: boolean, client?: WebUIMutationTransport) {
  let snapshot: Omit<VersionCheckState, "check" | "dismiss" | "changeChannel"> = {
    result: null, checking: false, dismissedVersion: null, installationMethod: null,
    releaseStatus: null, canChangeChannel: false, changingChannel: false, channelError: "",
  };
  let pending: Promise<void> | null = null;
  let pendingChannel: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const update = (patch: Partial<typeof snapshot>) => {
    snapshot = { ...snapshot, ...patch };
    listeners.forEach((listener) => listener());
  };
  const check = () => {
    if (pending) return pending;
    update({ checking: true });
    pending = (async () => {
      try {
        const response = await checkVersion(token, "", channels);
        if (channels && !response.releaseStatus) throw new Error("The gateway did not return its update channel. Check again.");
        const method = response.installation_method;
        update({ installationMethod: method && ["managed", "uv", "pipx", "pip", "source", "container", "system"].includes(method) ? method : null });
        if (channels && response.releaseStatus) update({ releaseStatus: response.releaseStatus, canChangeChannel: response.can_change_channel === true });
        update({ result: response.updateAvailable
          ? { type: "update", ...response.updateAvailable }
          : response.releaseStatus && response.releaseStatus.state !== "current"
            ? { type: "release-status", state: response.releaseStatus.state }
            : { type: "up-to-date" } });
      } catch (error) {
        update({ result: { type: "error", message: (error as Error).message } });
      } finally {
        pending = null;
        update({ checking: false });
      }
    })();
    return pending;
  };
  return {
    // Entering About during a save shares its post-mutation check, not an old-channel read.
    check: () => pendingChannel ?? check(),
    changeChannel: (channel: UpdateChannel) => {
      if (!channels || !client || !snapshot.releaseStatus || !snapshot.canChangeChannel || snapshot.changingChannel || pending) return Promise.resolve();
      const revision = snapshot.releaseStatus.revision;
      update({ changingChannel: true, channelError: "" });
      pendingChannel = (async () => {
        try {
          const selection = await changeUpdateChannel(client, channel, revision);
          update({ releaseStatus: { ...snapshot.releaseStatus!, ...selection }, result: null, dismissedVersion: null });
        } catch (error) {
          update({ channelError: (error as Error).message });
        } finally {
          // Also resolve a lost mutation response / another tab's newer revision.
          await check();
          pendingChannel = null;
          update({ changingChannel: false });
        }
      })();
      return pendingChannel;
    },
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    dismiss: () => {
      if (snapshot.result?.type === "update") update({ dismissedVersion: snapshot.result.latestVersion });
    },
  };
}

export function VersionCheckProvider({ token, channels = false, client, children }: {
  token: string;
  channels?: boolean;
  client?: WebUIMutationTransport;
  children: ReactNode;
}) {
  const store = useMemo(() => createVersionCheck(token, channels, client), [token, channels, client]);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);

  return <VersionCheckContext.Provider value={{ ...snapshot, check: store.check, dismiss: store.dismiss, changeChannel: store.changeChannel }}>
    {children}
  </VersionCheckContext.Provider>;
}

export function useVersionCheck() {
  const value = useContext(VersionCheckContext);
  if (!value) throw new Error("useVersionCheck must be used within a VersionCheckProvider");
  return value;
}
