import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { Check, ChevronDown, Info, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { SETTINGS_SEARCH_INPUT_CLASS, SettingsGroup, SettingsRow } from "@/components/settings/shared/SettingsControls";
import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { Button } from "@/components/ui/button";
import { DisclosureContent } from "@/components/ui/disclosure";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { linearMemberAccessStore } from "./member-access-store";
import { LinearAvatar } from "./LinearAvatar";

export function LinearMemberAccess({ organizationId, configScope = "", disabled = false }: {
  organizationId: string;
  configScope?: string;
  disabled?: boolean;
}) {
  const { client, token } = useClient();
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const [search, setSearch] = useState("");
  const store = linearMemberAccessStore(client, token, configScope, organizationId);
  const { payload, loading, error, saves } = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const members = payload?.members ?? [];
  const saving = Object.values(saves).some((save) => save.status === "saving");

  useEffect(() => {
    if (expanded && !disabled) void store.load();
  }, [store, expanded, disabled]);

  const prefetch = () => { if (!disabled) void store.load(); };
  const needle = search.trim().toLocaleLowerCase();
  const visible = members.filter((member) => [member.name, member.id, ...member.teams]
    .some((value) => value.toLocaleLowerCase().includes(needle)));
  const names = new Set<string>();
  const duplicateNames = new Set<string>();
  for (const member of members) {
    if (names.has(member.name)) duplicateNames.add(member.name);
    names.add(member.name);
  }

  return (
    <section className="w-full border-t border-border/50 bg-settings-surface">
      <button type="button" aria-expanded={expanded} aria-controls={panelId}
        disabled={disabled} onMouseEnter={prefetch} onFocus={prefetch}
        className="settings-list-inset flex min-h-12 w-full items-center justify-between gap-3 py-2 text-start text-[12px] font-medium settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50"
        onClick={() => setExpanded(!expanded)}>
        <span className="shrink-0">{tx("members.title", "Member access")}</span>
        <span className="flex min-w-0 items-center gap-2">
          <span role="status" aria-live="polite" className="text-end text-[11px] font-normal text-muted-foreground">
            {payload ? !expanded ? tx("members.summary", "{{allowed}} enabled", {
              allowed: members.filter((member) => member.allowed).length,
            }) : null : loading ? tx("members.loading", "Finding your teammates…") : null}
          </span>
          <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none", expanded && "rotate-180")} aria-hidden />
        </span>
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {payload && loading ? tx("members.refreshing", "Checking for updates…") : null}
      </span>
      <DisclosureContent id={panelId} open={expanded} className="space-y-3 pb-2">
        {payload?.legacy_allow_all ? <p className="settings-list-inset rounded-control bg-muted py-2 text-[12px] leading-5">
          {tx("members.allowAll", "Advanced settings currently allow all members (*), including new members. Individual off switches still take precedence. Remove * to require approval for new members.")}
        </p> : null}
        <div className="settings-list-inset flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input value={search} onChange={(event) => setSearch(event.target.value)}
              aria-label={tx("members.search", "Search members")}
              placeholder={tx("members.search", "Search members")}
              className={cn(SETTINGS_SEARCH_INPUT_CLASS, "pl-9 text-[13px]")} />
          </div>
          <Button type="button" variant="ghost" size="icon" disabled={disabled || loading || saving}
            onClick={() => void store.load(true)} aria-label={tx("members.refresh", "Refresh members")}
            title={tx("members.refresh", "Refresh members")}>
            <RefreshCw className="h-4 w-4 text-muted-foreground" aria-hidden />
          </Button>
          <SettingsHint description={tx("members.help", "Choose who can use nanobot in Linear without a pairing code. This does not grant access to the nanobot admin UI. Turning access off blocks new requests, not tasks already running.")}>
            <span className="flex h-9 w-9 items-center justify-center text-muted-foreground">
              <Info className="h-4 w-4" aria-hidden />
              <span className="sr-only">{tx("members.details", "About member access")}</span>
            </span>
          </SettingsHint>
        </div>
        {error ? <p role="alert" className="settings-list-inset break-words text-[12px] leading-5 text-destructive">
          {error} {tx("members.retry", "Refresh members to check the current state and try again.")}
        </p> : null}
        {payload && !error && visible.length === 0 ? <p className="settings-list-inset py-3 text-[12px] text-muted-foreground">
          {tx("members.empty", "No matching active members in the teams this app can access.")}
        </p> : null}
        <SettingsGroup>
          <ul className="max-h-80 overflow-y-auto" aria-label={tx("members.title", "Member access")}>
            {visible.map((member) => {
              const save = saves[member.id];
              const statusId = `${panelId}-${member.id}-status`;
              return <li key={member.id}>
                <SettingsRow title={<div className="flex min-w-0 items-center gap-3">
                  <LinearAvatar name={member.name} url={member.avatar_url} />
                  <div className="min-w-0">
                    <p className="truncate" title={member.id}>{member.name}</p>
                    <div className="flex flex-wrap items-center gap-x-2 text-[12px] font-normal text-muted-foreground">
                      <span className="truncate">{member.teams.join(" · ")}</span>
                      <span id={save?.status === "error" ? undefined : statusId} role="status" aria-live="polite" className="inline-flex items-center gap-1">
                        {save?.status === "saving" ? tx("members.working", "Saving…") : null}
                        {save?.status === "saved" ? <><Check className="h-3 w-3" aria-hidden />{tx("members.saved", "Saved")}</> : null}
                      </span>
                    </div>
                    {duplicateNames.has(member.name) ?
                      <p className="break-all text-[11px] font-normal text-muted-foreground">{member.id}</p> : null}
                  </div>
                </div>}>
                  <ToggleButton checked={member.allowed}
                    disabled={disabled || save?.status === "saving" || save?.status === "error"}
                    aria-describedby={save ? statusId : undefined} aria-invalid={save?.status === "error" || undefined}
                    label={tx("members.allow", "Allow {{name}} to use nanobot", { name: member.name })}
                    onChange={(allowed) => void store.setAllowed(member.id, allowed,
                      tx("members.saveUnconfirmed", "Access was not confirmed. Refresh members before trying again."))} />
                </SettingsRow>
                {save?.status === "error" ? <p id={statusId} role="alert" className="settings-list-inset break-words pb-3 text-[12px] leading-5 text-destructive">
                  {save.message} {tx("members.retry", "Refresh members to check the current state and try again.")}
                </p> : null}
              </li>;
            })}
          </ul>
        </SettingsGroup>
      </DisclosureContent>
    </section>
  );
}
