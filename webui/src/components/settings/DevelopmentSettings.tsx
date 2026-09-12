import { useCallback, useEffect, useRef, useState } from "react";
import { CodexLimits } from "@/components/CodexLimits";
import { Button } from "@/components/ui/button";
import { controlDevelopment, fetchDevelopment, type DevelopmentPayload } from "@/lib/operations";
import { useClient } from "@/providers/ClientProvider";

const STAGES: Record<string, string> = {
  queued: "W kolejce", baseline: "Sprawdzanie wersji wyjściowej", building: "Wprowadzanie zmiany",
  checking: "Testy", review: "Niezależna ocena", ready: "Sprawdzona zmiana, oczekuje na wdrożenie",
  deployed: "Wdrożone", failed: "Zatrzymane z błędem", cancelled: "Anulowane", held: "Wstrzymane",
};

export function DevelopmentSettings() {
  const { client, getToken } = useClient();
  const [payload, setPayload] = useState<DevelopmentPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (pending.current) return;
    const current = ++generation.current;
    try {
      const result = await fetchDevelopment(getToken(), signal);
      if (!signal?.aborted && current === generation.current) { setPayload(result); setError(null); }
    } catch (error) {
      if (!signal?.aborted && current === generation.current) setError(error instanceof Error ? error.message : "Nie udało się odczytać projektu.");
    }
  }, [getToken]);
  useEffect(() => {
    const abort = new AbortController();
    const update = () => { if (document.visibilityState !== "hidden") void refresh(abort.signal); };
    update();
    const timer = setInterval(update, 10_000);
    document.addEventListener("visibilitychange", update);
    return () => { abort.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", update); generation.current++; };
  }, [refresh]);
  const control = async (action: string, jobId?: string) => {
    if (pending.current) return;
    pending.current = true;
    generation.current++;
    setBusy(true);
    try { setPayload(await controlDevelopment(client, action, jobId)); setError(null); }
    catch (error) { setError(error instanceof Error ? error.message : "Nie udało się zmienić stanu."); }
    finally { pending.current = false; setBusy(false); }
  };
  const project = payload?.project;
  return <div className="space-y-6">
    <CodexLimits />
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {!payload && !error && <p role="status">Odczytywanie projektu…</p>}
    {payload && !payload.enabled && <p>Projekt rozwoju nie jest włączony w tym gatewayu.</p>}
    {project && <>
      <div className="space-y-3">
        <p className="font-medium">{project.paused ? "Rozwój wstrzymany" : "Rozwój aktywny"}</p>
        <p className="whitespace-pre-wrap text-sm">{project.objective}</p>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void control("continue")}>Kontynuuj</Button>
          <Button variant="outline" disabled={busy || project.paused} onClick={() => void control("pause")}>Wstrzymaj</Button>
          <Button variant="outline" disabled={busy} onClick={() => void refresh()}>Odśwież</Button>
        </div>
        {payload.message && <p role="status" className="text-sm">{payload.message}</p>}
      </div>
      <details className="rounded-xl border p-4"><summary className="cursor-pointer font-medium">Pełny zakres ({project.requirements.length})</summary>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm">{project.requirements.map((requirement) => <li key={requirement.id}>{requirement.description}</li>)}</ul>
      </details>
      <div className="space-y-3">{project.jobs.map((job) => <article key={job.id} className="space-y-2 rounded-xl border p-4">
        <div className="flex flex-wrap justify-between gap-2"><h2 className="font-medium">{job.title}</h2><span className="text-sm text-muted-foreground">{STAGES[job.stage] || job.stage}</span></div>
        <p className="text-sm">{job.objective}</p>
        {job.blocked_reason && <p role="status" className="text-sm text-destructive">{job.blocked_reason}</p>}
        <details><summary className="cursor-pointer text-sm">Kryteria i wyniki</summary>
          <ul className="my-2 list-disc pl-5 text-sm">{job.acceptance.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
          <p className="text-sm">Sprawdzenia: {job.verification.filter((item) => item.exit_code === 0).length}/{job.verification.length}. Ocena: {job.review_accepted ? "przyjęta" : "brak akceptacji"}.</p>
          {job.review && <p className="mt-2 whitespace-pre-wrap text-sm">{job.review}</p>}
          {job.notes.map((note, index) => <p key={index} className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">Notatka: {note}</p>)}
        </details>
        {job.stage === "queued" && <Button size="sm" variant="outline" disabled={busy || project.paused} onClick={() => void control("start", job.id)}>Uruchom zadanie</Button>}
      </article>)}</div>
    </>}
  </div>;
}
