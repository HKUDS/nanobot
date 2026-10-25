import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useClient } from "@/providers/ClientProvider";
import { remoteAction } from "@/lib/remote-instances";
import { useRemoteConnections } from "./remote-context";
import { PairRouteSettingsView } from "./PairRouteSettingsView";

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
  return <PairRouteSettingsView hasSavedRoute={hasSavedRoute}
    routes={connections?.directory?.profiles.filter((profile) => !profile.paired) ?? []}
    route={route} original={original} busy={busy} error={error} saved={saved} showHint={showHint}
    onRouteChange={(value) => { setRoute(value); setError(""); setSaved(false); }}
    onSave={() => { void save(); }} />;
}
