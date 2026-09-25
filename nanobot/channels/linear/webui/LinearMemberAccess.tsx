import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { manageLinearMembers } from "./api";
import type { LinearMember } from "./types";

export function LinearMemberAccess({ organizationId, disabled = false }: {
  organizationId: string;
  disabled?: boolean;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const [members, setMembers] = useState<LinearMember[]>([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [allowAll, setAllowAll] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, [organizationId]);

  const refresh = async () => {
    const request = ++generation.current;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const payload = await manageLinearMembers(client, { operation: "members", organization_id: organizationId });
      if (request !== generation.current) return;
      setMembers(payload.members);
      setAllowAll(payload.legacy_allow_all);
    } catch (err) {
      if (request === generation.current) setError((err as Error).message);
    } finally {
      if (request === generation.current) setBusy(false);
    }
  };

  const setAllowed = async (member: LinearMember, allowed: boolean) => {
    const request = ++generation.current;
    setBusy(true);
    setSavingId(member.id);
    setError(null);
    setSaved(false);
    try {
      const payload = await manageLinearMembers(client, {
        operation: "member_access", organization_id: organizationId, user_id: member.id, allowed,
      });
      if (request !== generation.current) return;
      const updated = payload.members.find((item) => item.id === member.id);
      if (!updated || updated.allowed !== allowed) throw new Error(tx("members.saveUnconfirmed", "Access was not confirmed. Refresh members before trying again."));
      setMembers((current) => current.map((item) => item.id === member.id ? updated : item));
      setAllowAll(payload.legacy_allow_all);
      setSaved(true);
    } catch (err) {
      if (request === generation.current) setError((err as Error).message);
    } finally {
      if (request === generation.current) {
        setBusy(false);
        setSavingId(null);
      }
    }
  };

  const needle = search.trim().toLocaleLowerCase();
  const visible = members.filter((member) => [member.name, member.id, ...member.teams]
    .some((value) => value.toLocaleLowerCase().includes(needle)));

  return (
    <section className="w-full border-t border-border/50 pt-2">
      <button type="button" aria-expanded={expanded} aria-controls={panelId}
        disabled={disabled || busy}
        className="flex min-h-10 w-full items-center justify-between gap-2 text-start text-[12px] font-medium disabled:opacity-50"
        onClick={() => {
          setExpanded(!expanded);
          if (!expanded) void refresh();
        }}>
        {tx("members.title", "Member access")}
        <ChevronDown className={cn("h-4 w-4", expanded && "rotate-180")} aria-hidden />
      </button>
      {expanded ? (
        <div id={panelId} className="space-y-3 pb-1">
          <p className="text-[12px] leading-5 text-muted-foreground">
            {tx("members.help", "Choose who can use nanobot in Linear without a pairing code. This does not grant access to the nanobot admin UI. Turning access off blocks new requests, not tasks already running.")}
          </p>
          {allowAll ? <p className="rounded-control bg-muted p-2 text-[12px] leading-5">
            {tx("members.allowAll", "Advanced settings currently allow all members (*), including new members. Individual off switches still take precedence. Remove * to require approval for new members.")}
          </p> : null}
          <div className="flex items-center gap-2">
            <Input value={search} onChange={(event) => setSearch(event.target.value)}
              aria-label={tx("members.search", "Search members")}
              placeholder={tx("members.search", "Search members")} className="min-w-0 text-[12px]" />
            <Button type="button" variant="ghost" size="sm" disabled={disabled || busy}
              onClick={() => void refresh()} aria-label={tx("members.refresh", "Refresh members")}>
              <RefreshCw className={cn("h-4 w-4", busy && !savingId && "animate-spin motion-reduce:animate-none")} aria-hidden />
            </Button>
          </div>
          <div role="status" aria-live="polite" className="text-[12px] text-muted-foreground">
            {busy ? tx("members.working", "Updating member access…") : saved ? <span className="inline-flex items-center gap-1">
              <Check className="h-3 w-3" aria-hidden />{tx("members.saved", "Member access saved.")}
            </span> : null}
          </div>
          {error ? <p role="alert" className="text-[12px] leading-5 text-destructive">
            {error} {tx("members.retry", "Refresh members to check the current state and try again.")}
          </p> : null}
          {!busy && !error && visible.length === 0 ? <p className="text-[12px] text-muted-foreground">
            {tx("members.empty", "No matching active members in the teams this app can access.")}
          </p> : null}
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {visible.map((member) => <li key={member.id} className="flex min-h-14 items-center gap-3 rounded-control px-2 py-2">
              <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
                {member.name.slice(0, 2).toLocaleUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12.5px] font-medium" title={member.id}>{member.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">{member.teams.join(" · ")}</p>
                {members.some((other) => other.id !== member.id && other.name === member.name) ?
                  <p className="truncate text-[10px] text-muted-foreground">{member.id}</p> : null}
              </div>
              {savingId === member.id ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              <ToggleButton checked={member.allowed} disabled={disabled || busy || Boolean(error)}
                label={tx("members.allow", "Allow {{name}} to use nanobot", { name: member.name })}
                onChange={(allowed) => void setAllowed(member, allowed)} />
            </li>)}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
