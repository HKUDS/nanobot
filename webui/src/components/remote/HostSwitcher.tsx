import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Check, ChevronUp, CircleAlert, Laptop, Loader2, Search, Server, Settings2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/lib/types";
import type { HostAnchor, EmbeddedHost } from "./host-bridge";
import { HostConnectionStatus, type HostConnectionState } from "./HostConnectionStatus";

export interface HostPicker {
  kind: "shell";
  name: string;
  hostname: string;
  localName: string;
  currentId: string | null;
  profiles: { id: string; name: string; host: string; state: HostConnectionState }[];
  recentIds: string[];
  pending: { id: string; name: string } | null;
  error: string;
  offline: boolean;
  offlineLabel?: string;
  select: (id: string | null) => void;
  manage: () => void;
  cancel: () => void;
  clearError: () => void;
  restoreFocus: () => void;
}
interface EmbeddedPicker extends EmbeddedHost {
  kind: "embedded";
  open: (anchor: HostAnchor) => void;
}
export const HostNavigationContext = createContext<HostPicker | EmbeddedPicker | null>(null);

function HostMenuContent({ picker, portalContainer }: { picker: HostPicker; portalContainer?: HTMLElement | null }) {
  return <DropdownMenuContent side="top" align="end" sideOffset={8} collisionPadding={12}
    portalContainer={portalContainer} className="flex w-64 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden"
    onEscapeKeyDown={(event) => { if (event.isComposing) event.preventDefault(); }}
    onCloseAutoFocus={(event) => { event.preventDefault(); picker.restoreFocus(); }}>
    <HostMenuItems picker={picker} />
  </DropdownMenuContent>;
}

/** Mounted with the menu so every opening starts with a fresh, stable list. */
function HostMenuItems({ picker }: { picker: HostPicker }) {
  const { t } = useTranslation();
  const [searchable] = useState(() => picker.profiles.length > 5);
  const [query, setQuery] = useState("");
  const [order] = useState(() => [picker.currentId, ...picker.recentIds]);
  const search = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const needle = query.trim().toLocaleLowerCase();
  const matches = (...values: string[]) => values.some((value) => value.toLocaleLowerCase().includes(needle));
  const showLocal = matches(t("remote.local"), picker.localName);
  const profiles = picker.profiles.filter(({ name, host }) => matches(name, host));
  if (searchable) {
    const rank = (id: string) => { const index = order.indexOf(id); return index < 0 ? order.length : index; };
    profiles.sort((a, b) => rank(a.id) - rank(b.id));
  }
  useEffect(() => {
    // Don't summon the software keyboard when opening the picker on a touch device.
    if (!searchable || window.matchMedia("(pointer: coarse)").matches) return;
    const frame = requestAnimationFrame(() => search.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [searchable]);

  return <div className="flex min-h-0 flex-col"
    onPointerMoveCapture={(event) => { if (document.activeElement === search.current) event.preventDefault(); }}
    onPointerOutCapture={(event) => { if (document.activeElement === search.current) event.preventDefault(); }}
    onKeyDownCapture={(event) => {
    if (!searchable) return;
    if (event.nativeEvent.isComposing) { event.stopPropagation(); return; }
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    if (event.target === search.current) {
      // Keep spaces and IME input out of Radix's menu typeahead.
      if (event.key !== "Escape") event.stopPropagation();
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Tab") {
        event.preventDefault();
        (event.key === "ArrowUp" || event.shiftKey ? items.at(-1) : items[0])?.focus();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (needle) list.current?.querySelector<HTMLElement>('[role="menuitem"]')?.click();
      }
    } else if (event.key === "Tab" || (event.key === "ArrowUp" && event.target === items[0])) {
      event.preventDefault(); event.stopPropagation(); search.current?.focus();
    }
  }}>
    {searchable ? <div className="flex shrink-0 items-center gap-2 px-2.5 pb-2 pt-1.5">
      <Search aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
      <input ref={search} aria-label={t("remote.searchHosts")} placeholder={t("remote.searchHosts")}
        value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" spellCheck={false}
        className="touch-text-input h-7 min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground" />
    </div> : <DropdownMenuLabel className="shrink-0">{t("remote.switchHost")}</DropdownMenuLabel>}
    <div ref={list} role="group" aria-label={t("remote.switchHost")}
      className="min-h-0 overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent">
    {showLocal && <DropdownMenuItem onSelect={() => picker.select(null)} className="gap-2.5" aria-current={!picker.currentId || undefined}>
      <Laptop className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1"><span className="block">{t("remote.local")}</span><span className="block truncate text-xs text-muted-foreground">{picker.localName}</span></span>
      {!picker.currentId && <Check className="h-4 w-4" />}
    </DropdownMenuItem>}
    {showLocal && !!profiles.length && <DropdownMenuSeparator />}
    {profiles.map((profile) => <DropdownMenuItem key={profile.id} onSelect={() => picker.select(profile.id)} className="gap-2.5"
      aria-label={`${profile.name} ${profile.host}`} aria-describedby={`host-state-${profile.id}`}
      title={`${profile.name} · ${profile.host}`} aria-current={picker.currentId === profile.id || undefined}>
      <Server className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1"><span className="block truncate">{profile.name}</span><span className="block truncate text-xs text-muted-foreground">{profile.host}</span></span>
      <span id={`host-state-${profile.id}`}><HostConnectionStatus state={profile.state} compact /></span>
      {picker.currentId === profile.id && <Check aria-label={t("remote.current")} className="h-4 w-4 shrink-0" />}
    </DropdownMenuItem>)}
    {!showLocal && !profiles.length && <p role="status" className="px-2.5 py-6 text-center text-xs text-muted-foreground">{t("remote.noMatchingHosts")}</p>}
    </div>
    <div className="shrink-0">
    {picker.pending && <><DropdownMenuSeparator /><DropdownMenuItem onSelect={picker.cancel} className="gap-2.5"><X className="h-4 w-4" />{t("remote.cancelSwitch")}</DropdownMenuItem></>}
    {picker.error && <div role="alert" className="flex items-start gap-2 px-2.5 py-2 text-xs leading-5 text-foreground">
      <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{picker.error}<button className="ml-2 underline underline-offset-2" onClick={picker.clearError}>{t("common.close")}</button></span>
    </div>}
    <DropdownMenuSeparator />
    <DropdownMenuItem className="gap-2.5" onSelect={picker.manage}><Settings2 className="h-4 w-4 text-muted-foreground" />{t("remote.manageConnections")}</DropdownMenuItem>
    </div>
  </div>;
}

/** Shared sidebar control. Remote frames can only open the trusted shell's menu. */
export function HostSwitcher({ collapsed = false, portalContainer }: { collapsed?: boolean; portalContainer?: HTMLElement | null }) {
  const picker = useContext(HostNavigationContext);
  const { client } = useClient();
  const { t } = useTranslation();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  useEffect(() => client.onStatus(setStatus), [client]);
  const buttonRef = useRef<HTMLButtonElement>(null);
  if (!picker) return <ConnectionBadge />;
  const shell = picker.kind === "shell" ? picker : null;
  const remote = picker.kind === "embedded" || !!shell?.currentId;
  const pendingName = picker.kind === "shell" ? picker.pending?.name : picker.pendingName;
  const currentStatus = shell?.currentId
    ? (shell.pending?.id === shell.currentId || shell.profiles.find((profile) => profile.id === shell.currentId)?.state === "connecting" ? "connecting" : shell.offline ? "closed" : "open")
    : status;
  // A failed switch describes the destination, not the still-active connection.
  const failed = !!shell?.offline || currentStatus === "error" || currentStatus === "closed";
  const waiting = !!pendingName || currentStatus === "connecting" || currentStatus === "reconnecting";
  // The old host stays interactive until the new one is ready. Keep its identity
  // visible; progress belongs to the target's row and the accessible status.
  const label = picker.name;
  const currentLabel = failed ? shell?.offlineLabel || t("remote.offline") : t(`connection.${currentStatus}`);
  const identity = picker.name === picker.hostname ? picker.name : `${picker.name} · ${picker.hostname}`;
  const current = `${identity} · ${currentLabel}`;
  const detail = pendingName ? `${current} · ${t("remote.preparing", { name: pendingName })}` : current;
  const title = picker.error ? `${detail} — ${picker.error}` : detail;
  const button = <Button ref={buttonRef} variant="ghost" size="sm" aria-label={t("remote.switchHost")} title={title}
    data-host-switcher className={cn("host-no-drag h-8 min-w-0 gap-2 rounded-xl px-2 text-xs font-normal text-sidebar-content/75 hover:bg-sidebar-accent/65 hover:text-sidebar-content",
      collapsed ? "w-8 justify-center px-0" : "max-w-full flex-1 justify-start")}
    onClick={picker.kind === "embedded" ? () => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (rect) picker.open({ left: rect.left, top: rect.top, width: rect.width, height: rect.height });
    } : undefined}>
    <span className="relative flex shrink-0 items-center justify-center">
      {waiting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : failed ? <CircleAlert className="h-4 w-4" />
        : remote ? <Server className="h-4 w-4" /> : <Laptop className="h-4 w-4" />}
      {!waiting && !failed && <span aria-hidden className={cn("absolute -bottom-0.5 -right-0.5 h-1.5 w-1.5 rounded-full ring-2 ring-sidebar", currentStatus === "open" ? "bg-emerald-500" : "bg-muted-foreground")} />}
    </span>
    {!collapsed && <><span className="truncate">{label}</span><ChevronUp className="ml-auto h-3 w-3 shrink-0 opacity-60" /></>}
    <span className="sr-only" role="status">{detail}</span>
  </Button>;
  if (!shell) return button;
  // The mobile sidebar already owns the modal lock; a nested lock can outlive it on navigation.
  return <DropdownMenu modal={!portalContainer}><DropdownMenuTrigger asChild>{button}</DropdownMenuTrigger><HostMenuContent picker={shell} portalContainer={portalContainer} /></DropdownMenu>;
}

/** Parent-owned menu anchored to the active remote sidebar, never inside its DOM. */
export function RemoteHostMenu({ picker, anchor, onClose }: { picker: HostPicker; anchor: HostAnchor | null; onClose: () => void }) {
  return <DropdownMenu open={!!anchor} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DropdownMenuTrigger asChild><button tabIndex={-1} aria-hidden className="pointer-events-none fixed opacity-0" style={anchor ? {
      left: Math.max(0, Math.min(anchor.left, window.innerWidth - 32)), top: Math.max(0, Math.min(anchor.top, window.innerHeight - 32)),
      width: Math.min(anchor.width, window.innerWidth), height: Math.min(anchor.height, 64),
    } : { width: 0, height: 0 }} /></DropdownMenuTrigger>
    <HostMenuContent picker={picker} />
  </DropdownMenu>;
}
