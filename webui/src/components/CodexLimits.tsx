import { useEffect, useState } from "react";
import { fetchCodexLimits, quotaDuration, quotaSummary, type CodexQuotaSnapshot } from "@/lib/operations";
import { useClient } from "@/providers/ClientProvider";

export function CodexLimits({ compact = false }: { compact?: boolean }) {
  const { getToken } = useClient();
  const [snapshot, setSnapshot] = useState<CodexQuotaSnapshot | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      try {
        const result = await fetchCodexLimits(getToken(), abort.signal);
        if (!abort.signal.aborted) setSnapshot(result);
      } catch {
        if (!abort.signal.aborted) setSnapshot((previous) => previous
          ? { ...previous, state: "stale", error: "Nie udało się odświeżyć limitów." } : null);
      } finally { pending = false; }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 30_000);
    document.addEventListener("visibilitychange", refresh);
    return () => { abort.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [getToken]);
  if (!snapshot?.enabled) return null;
  const updated = snapshot.observed_at ? new Date(snapshot.observed_at * 1000).toLocaleString() : "brak odczytu";
  if (compact) return <div className="px-3 py-1 text-[11px] text-muted-foreground" title={`Wykorzystanie limitu konta Codex CLI. Odczyt: ${updated}`}>
    {quotaSummary(snapshot)}
  </div>;
  return <section aria-label="Limity Codex" className="space-y-3 rounded-xl border p-4">
    <h2 className="font-medium">Limity Codex</h2>
    <p className="text-sm text-muted-foreground">Limity konta Codex CLI · odczyt: {updated}</p>
    {snapshot.gateway_account_matches === false && <p role="status">To inne konto niż konto Codex używane przez gateway.</p>}
    {snapshot.buckets.map((bucket) => <div key={bucket.limit_id} className="space-y-2">
      <p className="text-sm font-medium">{bucket.limit_name || bucket.limit_id}</p>
      {[bucket.primary, bucket.secondary].map((window, index) => window && <div key={index}>
        <div className="flex justify-between text-sm"><span>Okno {quotaDuration(window.window_duration_mins)}</span><span>{window.used_percent}% wykorzystane</span></div>
        <progress aria-label={`${bucket.limit_name || bucket.limit_id}, ${quotaDuration(window.window_duration_mins)}`} max={100} value={Math.min(100, window.used_percent)} className="h-2 w-full" />
        <p className="text-xs text-muted-foreground">Odnowienie: {window.resets_at ? new Date(window.resets_at * 1000).toLocaleString() : "brak danych"}</p>
      </div>)}
    </div>)}
    {snapshot.state === "stale" && <p role="status" className="text-sm">Dane nieaktualne — ostatni poprawny odczyt zachowano powyżej.</p>}
    {snapshot.error && <p role="status" className="text-sm">{snapshot.error}</p>}
  </section>;
}
