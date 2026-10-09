import { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useClient } from "@/providers/ClientProvider";
import { remoteAction } from "@/lib/remote-instances";
import { useRemoteConnections } from "./RemoteInstances";

/** An explicit escape hatch for a VPN/bound-interface route, not a new SSH form. */
export function PairRouteSettings({ id, onSaved, showHint = true }: { id: string; onSaved?: () => void; showHint?: boolean }) {
  const { t } = useTranslation();
  const { client } = useClient();
  const connections = useRemoteConnections();
  const hasSavedRoute = !!connections?.directory?.profiles.find((profile) => profile.id === id)?.ssh_config;
  const [route, setRoute] = useState(hasSavedRoute ? "saved" : "direct");
  const [original, setOriginal] = useState(route);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const save = async () => {
    setBusy(true); setError(""); setSaved(false);
    try {
      await remoteAction(client, "pair_route", { id, route_id: route === "direct" ? "" : route });
      if (!alive.current) return;
      // Saving and refreshing are different outcomes. Never invite a second save
      // merely because the directory refresh failed after the write succeeded.
      setOriginal(route); setSaved(true);
      try { await connections?.refresh(); }
      catch {
        if (alive.current) setError(t("remote.errors.directory_unavailable"));
        return;
      }
      if (alive.current) onSaved?.();
    } catch (reason) {
      if (alive.current) setError(t(`remote.errors.${reason instanceof Error ? reason.message : "unknown"}`, { defaultValue: t("remote.errors.unknown") }));
    } finally { if (alive.current) setBusy(false); }
  };
  return <div className="space-y-3">
    {showHint && <p className="text-xs leading-5 text-muted-foreground">{t("remote.pair.routeHint")}</p>}
    <Select value={route} onValueChange={(value) => { setRoute(value); setError(""); setSaved(false); }} disabled={busy}><SelectTrigger className="w-full min-w-0" aria-label={t("remote.pair.route")}><SelectValue /></SelectTrigger>
      <SelectContent>
        {hasSavedRoute && <SelectItem value="saved">{t("remote.pair.savedRoute")}</SelectItem>}
        <SelectItem value="direct">{t("remote.pair.direct")}</SelectItem>
        {connections?.directory?.profiles.filter((profile) => !profile.paired).map((profile) => <SelectItem key={profile.id} value={profile.id} className="h-auto min-h-9 max-w-[calc(100vw-3rem)] py-2 [overflow-wrap:anywhere]">{profile.name}</SelectItem>)}
      </SelectContent>
    </Select>
    {error && <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>}
    <div className="flex flex-wrap items-center justify-end gap-3">
      {saved && <p role="status" className="mr-auto flex items-center gap-1.5 text-xs text-muted-foreground"><Check aria-hidden className="h-3.5 w-3.5" />{t("remote.saved")}</p>}
      <Button className="remote-action" size="sm" disabled={busy || route === original || route === "saved"} aria-busy={busy} onClick={() => { void save(); }}>
        {busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />}{t(busy ? "remote.saving" : "remote.save")}
      </Button>
    </div>
  </div>;
}
