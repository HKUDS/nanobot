import { useId, useRef, type RefObject } from "react";
import { Check, RefreshCw, Server } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SSHDiscovery } from "@/lib/remote-instances";

export interface SSHHostPickerViewProps {
  disabled: boolean;
  value: string;
  imported: boolean;
  suggestions?: boolean;
  customConfig?: boolean;
  discovery: SSHDiscovery | null;
  busy: boolean;
  error: string;
  onRefresh: () => void;
  onChange: (host: string) => void;
  onBlur: () => void;
  inputRef: RefObject<HTMLInputElement>;
}

export function SSHHostPickerView({ disabled, value, imported, suggestions = true, customConfig = false,
  discovery, busy, error, onRefresh, onChange, onBlur, inputRef }: SSHHostPickerViewProps) {
  const { t } = useTranslation();
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const data = suggestions ? discovery : null;
  const matched = (data?.hosts ?? []).filter(({ host }) => host.toLowerCase().includes(value.trim().toLowerCase()));
  // A user recovering from a failed user@IP connection may select a custom
  // config containing an alias. Keep that alias discoverable without asking
  // them to know it already or silently replacing the address they entered.
  const hosts = matched.length || !customConfig ? matched : (data?.hosts ?? []);
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
          disabled={busy || disabled} onClick={onRefresh}>
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
