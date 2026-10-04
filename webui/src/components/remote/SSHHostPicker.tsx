import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";
import { Check, RefreshCw, Server } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useClient } from "@/providers/ClientProvider";
import { remoteAction, type SSHDiscovery } from "@/lib/remote-instances";

/** One address field for both manual entry and existing SSH aliases. */
export function SSHHostPicker({ disabled, value, configFile, imported, suggestions = true, onChange, onBlur, inputRef }: {
  disabled: boolean;
  value: string;
  configFile: string;
  imported: boolean;
  suggestions?: boolean;
  onChange: (host: string) => void;
  onBlur: () => void;
  inputRef: RefObject<HTMLInputElement>;
}) {
  const { t } = useTranslation();
  const { client } = useClient();
  const id = useId();
  const [result, setResult] = useState<{ file: string; data: SSHDiscovery } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const mounted = useRef(true);
  const list = useRef<HTMLDivElement>(null);
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
  const matched = (data?.hosts ?? []).filter(({ host }) => host.toLowerCase().includes(value.trim().toLowerCase()));
  // A user recovering from a failed user@IP connection may select a custom
  // config containing an alias. Keep that alias discoverable without asking
  // them to know it already or silently replacing the address they entered.
  const hosts = matched.length || !file ? matched : (data?.hosts ?? []);
  return <div className="space-y-2.5">
    <label htmlFor={id} className="block text-[13px] font-medium">{t("remote.host")}</label>
    <Input ref={inputRef} id={id} value={value} required disabled={disabled} autoComplete="off" spellCheck={false}
      placeholder={t("remote.hostPlaceholder")} aria-describedby={`${id}-hint`}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" && hosts.length && !busy) {
          event.preventDefault(); list.current?.querySelector<HTMLButtonElement>("button")?.focus();
        }
      }} />
    <p id={`${id}-hint`} role={imported ? "status" : undefined} className="text-xs leading-5 text-muted-foreground">{t(imported ? "remote.commandImported" : suggestions ? "remote.commandHint" : "remote.addressHint")}</p>
    {suggestions && (!!hosts.length || !!error) && <div className="rounded-2xl bg-muted/40 p-1.5">
      <div className="flex min-h-8 items-center justify-between gap-2 px-2">
        <span className="text-xs text-muted-foreground">{t("remote.sshHosts")}</span>
        <Button type="button" variant="ghost" size="icon" className="h-7 w-7 shrink-0" aria-label={t("remote.refreshHosts")}
          disabled={busy || disabled} onClick={() => { void load(file); }}>
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
        </Button>
      </div>
      <div ref={list} className="max-h-36 overflow-y-auto" aria-label={t("remote.sshHosts")}>
        {hosts.map((host, index) => <button key={host.host} type="button" disabled={disabled || busy}
          title={host.source} aria-label={t("remote.useHost", { host: host.host })}
          className="flex min-h-9 w-full items-center gap-2.5 rounded-xl px-2 text-left text-[13px] transition-colors hover:bg-foreground/5 focus-visible:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50"
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const next = index + (event.key === "ArrowDown" ? 1 : -1);
              if (next < 0) inputRef.current?.focus();
              else list.current?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
            }
          }}
          onClick={() => { onChange(host.host); inputRef.current?.focus(); }}>
          <Server className="h-4 w-4 shrink-0 text-muted-foreground" /><span className="min-w-0 flex-1 truncate">{host.host}</span>
          {value === host.host && <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
        </button>)}
      </div>
      {error && <p role="alert" className="px-2 py-1 text-xs leading-5 text-muted-foreground">{error}</p>}
    </div>}
    {data?.incomplete && <p className="text-xs leading-5 text-muted-foreground">{t("remote.partialHosts")}</p>}
  </div>;
}
