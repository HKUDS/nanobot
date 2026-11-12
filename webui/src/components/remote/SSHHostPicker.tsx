import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useClient } from "@/providers/ClientProvider";
import { remoteAction, type SSHDiscovery } from "@/lib/remote-instances";
import { SSHHostPickerView, type SSHHostPickerViewProps } from "./SSHHostPickerView";

type SSHHostPickerProps = Pick<SSHHostPickerViewProps,
  "disabled" | "value" | "imported" | "suggestions" | "onChange" | "onBlur" | "inputRef"> & {
  configFile: string;
};

/** One address field for both manual entry and existing SSH aliases. */
export function SSHHostPicker({ configFile, suggestions = true, ...props }: SSHHostPickerProps) {
  const { t } = useTranslation();
  const { client } = useClient();
  const [result, setResult] = useState<{ file: string; data: SSHDiscovery } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const mounted = useRef(true);
  const file = configFile.trim();
  const load = useCallback(async (path: string) => {
    const request = ++requestId.current;
    setBusy(true); setError("");
    try {
      const next = await remoteAction<SSHDiscovery>(client, "discover", { ssh_config: path });
      if (!next || !Array.isArray(next.hosts) || !Array.isArray(next.files)
        || typeof next.incomplete !== "boolean" || next.hosts.some((host) => !host
          || typeof host.host !== "string" || typeof host.source !== "string" || typeof host.ssh_config !== "string")) {
        throw new Error("discovery_failed");
      }
      if (mounted.current && request === requestId.current) setResult({ file: path, data: next });
    } catch (reason) {
      if (mounted.current && request === requestId.current) {
        const code = reason instanceof Error ? reason.message : "unknown";
        setError(t(`remote.errors.${code}`, { defaultValue: t("remote.discoveryError") }));
      }
    } finally {
      if (mounted.current && request === requestId.current) setBusy(false);
    }
  }, [client, t]);
  useEffect(() => {
    mounted.current = true;
    if (!suggestions) return;
    let started = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = client.onStatus((status) => {
      if (status === "open" && !started) {
        started = true;
        // Custom paths update quietly after typing; no separate "read config" flow.
        timer = setTimeout(() => { void load(file); }, file ? 300 : 0);
      }
    });
    return () => { mounted.current = false; requestId.current += 1; clearTimeout(timer); unsubscribe(); };
  }, [client, file, load, suggestions]);

  // Never select cached suggestions belonging to a different config file.
  const data = suggestions && result?.file === file ? result.data : null;
  return <SSHHostPickerView {...props} suggestions={suggestions} customConfig={!!file}
    discovery={data} busy={busy} error={error} onRefresh={() => { void load(file); }} />;
}
