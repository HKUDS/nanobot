import { AlertCircle, Check, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { RemoteProfile } from "@/lib/remote-instances";

export interface PairRouteSettingsViewProps {
  hasSavedRoute: boolean;
  routes: Array<Pick<RemoteProfile, "id" | "name">>;
  route: string;
  original: string;
  busy: boolean;
  error: string;
  saved: boolean;
  showHint?: boolean;
  onRouteChange: (route: string) => void;
  onSave: () => void;
}

export function PairRouteSettingsView({
  hasSavedRoute, routes, route, original, busy, error, saved, showHint = true, onRouteChange, onSave,
}: PairRouteSettingsViewProps) {
  const { t } = useTranslation();
  return <div className="space-y-3">
    {showHint && <p className="text-xs leading-5 text-muted-foreground">{t("remote.pair.routeHint")}</p>}
    <Select value={route} onValueChange={onRouteChange} disabled={busy}><SelectTrigger className="w-full min-w-0" aria-label={t("remote.pair.route")}><SelectValue /></SelectTrigger>
      <SelectContent>
        {hasSavedRoute && <SelectItem value="saved">{t("remote.pair.savedRoute")}</SelectItem>}
        <SelectItem value="direct">{t("remote.pair.direct")}</SelectItem>
        {routes.map((profile) => <SelectItem key={profile.id} value={profile.id} className="h-auto min-h-9 max-w-[calc(100vw-3rem)] py-2 [overflow-wrap:anywhere]">{profile.name}</SelectItem>)}
      </SelectContent>
    </Select>
    {error && <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>}
    <div className="flex flex-wrap items-center justify-end gap-3">
      {saved && <p role="status" className="mr-auto flex items-center gap-1.5 text-xs text-muted-foreground"><Check aria-hidden className="h-3.5 w-3.5" />{t("remote.saved")}</p>}
      <Button className="remote-action" size="sm" disabled={busy || route === original || route === "saved"} aria-busy={busy} onClick={onSave}>
        {busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />}{t(busy ? "remote.saving" : "remote.save")}
      </Button>
    </div>
  </div>;
}
