import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogDescription } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { UpdateGuide } from "@/components/UpdateGuide";
import { ApiError, createUpdateReview, readUpdateReview, readUpdateJob, prepareUpdate, executeUpdate, settleUpdate,
  type UpdateReviewResponse, type UpdateJob } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";

const STORAGE_KEY = "nanobot.pending-update.v1";
const RECOVERY_KEY = "nanobot.pending-update-recovery.v1";
const terminal = new Set(["preparation_failed", "handoff_failed", "restart_failed", "succeeded", "failed", "cancelled"]);
const UpdateFlowContext = createContext<{ open: (() => void) | undefined; pending: boolean }>({ open: undefined, pending: false });

function savedJob(): string | null {
  try {
    const id = sessionStorage.getItem(STORAGE_KEY);
    return id && /^[0-9a-f-]{36}$/.test(id) ? id : null;
  } catch { return null; }
}
function remember(id: string | null) {
  try { if (id) sessionStorage.setItem(STORAGE_KEY, id); else { sessionStorage.removeItem(STORAGE_KEY); sessionStorage.removeItem(RECOVERY_KEY); } } catch { /* Memory state still works. */ }
}

export function UpdateFlowProvider({ client, token, enabled, canSettleHandoff = false, children }: {
  client: NanobotClient; token: string; enabled: boolean; canSettleHandoff?: boolean; children: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [review, setReview] = useState<UpdateReviewResponse | null>(null);
  const [job, setJob] = useState<UpdateJob | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const [delayed, setDelayed] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [recovery, setRecovery] = useState("");
  const [automaticRecovery, setAutomaticRecovery] = useState(false);
  const generation = useRef(0);
  const approved = useRef<string | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const inFlight = useRef(false);

  // Credentials/host changes revoke this client's unconsumed consent. Restoring
  // a durable job is a read only; READY after refresh needs another button press.
  useEffect(() => {
    generation.current++;
    approved.current = null;
    inFlight.current = false;
    setSubmitting(false);
    setCheckingStatus(false);
    setReview(null);
    setJob(null);
    setError("");
    const id = enabled ? savedJob() : null;
    // Retain a plain-text host command for an offline gateway, never consent.
    // It is displayed, not executed by the browser.
    try {
      const saved = JSON.parse(sessionStorage.getItem(RECOVERY_KEY) || "null");
      setRecovery(saved?.id === id && typeof saved.command === "string" ? saved.command : "");
      setAutomaticRecovery(saved?.id === id && saved.automatic === true);
    } catch { setRecovery(""); setAutomaticRecovery(false); }
    setPendingId(id);
    setOpen(!!id);
  }, [client, token, enabled]);

  const execute = useCallback(async (id: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    const current = generation.current;
    approved.current = null; // Consume once before the request, including a lost response.
    try {
      const response = await executeUpdate(client, id);
      if (generation.current === current) setJob(response.job);
    } catch {
      // The gateway may already be shutting down. Read the journal before
      // offering a fresh confirmation; never replay execution automatically.
      if (generation.current === current) setError(t("updates.confirmationUnknown"));
    } finally {
      if (generation.current === current) { inFlight.current = false; setSubmitting(false); }
    }
  }, [client, t]);

  useEffect(() => {
    if (!enabled || !pendingId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let missingSince = 0;
    const reconnecting = () => {
      missingSince ||= Date.now();
      setOffline(true);
      setDelayed(Date.now() - missingSince > 120_000);
    };
    const refresh = async (manual = false) => {
      const feedback = manual ? new Promise(resolve => setTimeout(resolve, 600)) : Promise.resolve();
      try {
        // API tokens belong to a gateway process. Let the client's authenticated
        // reconnect replace them before reading the new process's update journal.
        if (client.status !== "open") {
          reconnecting();
          timer = setTimeout(() => void refresh(), 1500);
          return;
        }
        const { job: next } = await readUpdateJob(token, pendingId).finally(() => feedback);
        if (!active) return;
        setJob(next);
        setAutomaticRecovery(next.automatic_recovery === true);
        if (next.recovery_command) {
          setRecovery(next.recovery_command);
          try { sessionStorage.setItem(RECOVERY_KEY, JSON.stringify({ id: next.id, command: next.recovery_command, automatic: next.automatic_recovery === true })); } catch { /* Still available until reload. */ }
        }
        setOffline(false);
        setDelayed(false);
        missingSince = 0;
        setError("");
        if (next.recorded_phase === "ready" && approved.current === next.id) {
          await execute(next.id);
        }
        if (!active) return;
        if (!next.recovery_active && terminal.has(next.recorded_phase)
          && !(next.recorded_phase === "succeeded" && next.running_version !== next.target_version)
          && !(next.service_restored && next.running_version !== next.previous_version)) return;
        // A refresh can recover files already staged, but not installation consent.
        if (next.recorded_phase === "ready" && !next.execution_confirmation_id) {
          try {
            const restored = await readUpdateReview(token, next.id);
            if (active) setReview(restored);
          } catch { if (active) setError(t("updates.reviewFailed")); }
        }
      } catch (reason) {
        if (!active) return;
        if (reason instanceof ApiError && ([403, 404, 409].includes(reason.status)
          || (reason.status === 401 && client.status === "open"))) {
          // Do not discard an unknown mutation outcome or create a second job.
          approved.current = null;
          setOffline(false);
          setDelayed(false);
          setError(t("updates.statusFailed"));
          return;
        }
        reconnecting();
      } finally {
        if (manual) {
          // A repeated terminal result still needs a visible acknowledgement.
          await feedback;
          if (active) setCheckingStatus(false);
        }
      }
      if (active) timer = setTimeout(() => void refresh(), 1500);
    };
    void refresh(pollAttempt > 0);
    return () => { active = false; clearTimeout(timer); };
  }, [client, enabled, pendingId, token, execute, t, pollAttempt]);

  const inspect = async (retireId?: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = ++generation.current;
    approved.current = null;
    setSubmitting(true);
    setError("");
    let retired = !retireId;
    try {
      if (retireId) {
        // Only the gateway can establish that no old worker can still execute.
        // A lost/refused response keeps the original job and recovery entry.
        const response = await settleUpdate(client, retireId);
        if (generation.current !== current) return;
        if ((response.job.recorded_phase !== "cancelled" && response.job.recorded_phase !== "preparation_failed")
          || response.job.mutation_started) throw new Error("Update not settled");
        retired = true;
      }
      setJob(null);
      setReview(null);
      setRecovery("");
      setAutomaticRecovery(false);
      setPendingId(null);
      remember(null);
      const next = await createUpdateReview(client);
      if (generation.current === current) setReview(next);
    } catch {
      if (generation.current === current) setError(t(retired ? "updates.reviewFailed" : "updates.settleFailed"));
    } finally {
      if (generation.current === current) { setSubmitting(false); inFlight.current = false; }
    }
  };
  const show = () => {
    trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpen(true);
    if (!pendingId) void inspect();
  };
  const confirm = async () => {
    if (inFlight.current || !review?.execution_available || !review.installation_allowed) return;
    const id = review.plan.id;
    if (job?.recorded_phase === "ready") {
      if (job.execution_confirmation_id) return;
      await execute(id);
      setPollAttempt(value => value + 1);
      return;
    }
    inFlight.current = true;
    const current = generation.current;
    approved.current = id;
    setSubmitting(true);
    setError("");
    remember(id);
    setAutomaticRecovery(review.plan.automatic_recovery === true);
    try { sessionStorage.setItem(RECOVERY_KEY, JSON.stringify({ id, automatic: review.plan.automatic_recovery === true })); } catch { /* Memory state still works. */ }
    try {
      const response = await prepareUpdate(client, id);
      if (generation.current === current) { setJob(response.job); setPendingId(id); }
    } catch (reason) {
      if (generation.current === current) {
        approved.current = null;
        // A completed rejection (for example, a channel change in another tab)
        // plus a missing journal permits a new review, never automatic retry.
        // A timeout/lost response or an unreadable/existing job is still unknown.
        if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) {
          try {
            const response = await readUpdateJob(token, id);
            if (generation.current === current) setJob(response.job);
          } catch (readError) {
            if (generation.current !== current) return;
            if (readError instanceof ApiError && readError.status === 404) {
              remember(null);
              setReview(null);
              setError(t("updates.reviewAgainDescription"));
              return;
            }
          }
        }
        if (generation.current === current) setPendingId(id);
      }
    } finally {
      if (generation.current === current) { setSubmitting(false); inFlight.current = false; }
    }
  };

  const phase = job?.recorded_phase;
  const restored = job?.service_restored && job.running_version === job.previous_version;
  const done = restored || (phase === "succeeded" && job?.running_version === job?.target_version);
  const awaitingRestart = phase === "succeeded" && !done;
  const failed = !job?.recovery_active && !job?.service_restored && !!phase && terminal.has(phase) && phase !== "succeeded";
  // Backup can fail after shutdown/admission but before any package mutation.
  // That saved job still needs the standalone recovery path, not another update.
  const needsRecovery = failed && (job?.mutation_started || phase === "failed");
  const preparing = phase === "preparation_requested" || phase === "preparing";
  // The base update flow can settle preparation, but only the gateway's leases
  // establish abandonment. Keep this tab's confirmed preparation uninterrupted.
  const reviewAgain = job && !job.mutation_started && ((enabled && preparing && approved.current !== job.id)
    || (canSettleHandoff && (phase === "handoff_failed" || phase === "cancelled"
      || (phase === "ready" && review && review.plan.validity !== "current"))));
  const restoringReview = !!pendingId && phase === "ready" && !job?.execution_confirmation_id && !review && !error;
  const reviewing = (submitting && (!review || !!reviewAgain)) || restoringReview;
  const busy = checkingStatus || submitting || restoringReview || (!!pendingId && !reviewAgain && !error && !failed && !done && (phase !== "ready" || !!job?.execution_confirmation_id));
  const title = restored ? "restored" : done ? "done" : offline || awaitingRestart ? "reconnecting" : reviewing ? "reviewingTitle" : busy ? preparing ? "preparing" : phase === "installing" ? "installing" : "working" : failed ? "failed" : "confirm";
  const blocked = !reviewAgain && !job?.execution_confirmation_id && review && (!review.installation_allowed ? "permission" : review.plan.execution_blocked_reason);
  const guide = blocked && !busy && !error && !pendingId && review && ["upgrade", "restart"].includes(review.plan.action)
    && review.plan.validity === "current" ? review.plan.guide : null;
  const description = delayed ? t(automaticRecovery ? "updates.automaticRecovery" : "updates.delayed") : error || (restored ? t("updates.restoredDescription", { version: job?.previous_version }) : done ? t("updates.doneDescription", { version: job?.target_version })
    : offline || awaitingRestart ? t("updates.reconnectingDescription") : reviewing ? t("updates.reviewing")
    : reviewAgain ? t("updates.reviewAgainDescription") : failed ? t(job?.mutation_started ? "updates.repairRequired" : needsRecovery ? "updates.recoveryBeforeInstall" : "updates.preparationFailed")
    : busy ? t("updates.workingDescription") : guide?.reason === "restart" ? t("updates.guide.reasons.restart") : blocked ? t(`updates.blocked.${blocked}`)
    : review ? t("updates.confirmDescription", { version: review.plan.target_version, host: review.plan.host }) : t("updates.reviewing"));
  const startAgain = !pendingId || (failed && !needsRecovery && !job?.execution_confirmation_id);
  const primary = () => {
    if (checkingStatus) return;
    if (done) close();
    else if (reviewAgain && !error) {
      void inspect(job.id);
    } else if (error || failed) {
      if (startAgain) void inspect();
      else { setCheckingStatus(true); setPollAttempt(value => value + 1); }
    } else void confirm();
  };
  const close = () => { setOpen(false); if (done) { remember(null); setPendingId(null); window.location.reload(); } };
  const ownerInstructions = <a className="mt-3 block rounded-control text-sm text-muted-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href="https://github.com/HKUDS/nanobot/blob/main/docs/updating.md#installation-owners"
    target="_blank" rel="noreferrer">{t("updates.ownerGuide")}</a>;

  return <UpdateFlowContext.Provider value={{ open: enabled ? show : undefined, pending: enabled && !!pendingId }}>
    {children}
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogContent className={`max-h-[calc(100dvh-2rem)] ${guide ? "flex max-w-lg flex-col overflow-hidden" : "max-w-[384px] overflow-y-auto"} gap-0 rounded-panel p-6 motion-reduce:animate-none`}
        onOpenAutoFocus={(event) => { event.preventDefault(); heading.current?.focus(); }}
        onCloseAutoFocus={(event) => { event.preventDefault(); if (trigger.current?.isConnected) trigger.current.focus(); }}>
        <div aria-live="polite" aria-atomic="true">
          <img src="/brand/nanobot_mark.svg" alt="" draggable={false} className="mb-4 h-11 w-11 select-none" />
          <AlertDialogTitle ref={heading} tabIndex={-1} className="text-lg font-semibold leading-7 tracking-tight outline-none">{guide
            ? guide.reason === "restart" ? t("updates.guide.verifyTitle") : t("updates.guide.entry", { method: t(`updates.guide.methods.${guide.method}`) })
            : t(checkingStatus ? "settings.about.checking" : `updates.${title}`)}</AlertDialogTitle>
          <AlertDialogDescription className="mt-2 text-sm leading-6">{description}</AlertDialogDescription>
          {review?.plan.automatic_recovery && !pendingId && !busy && !blocked && !error &&
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{t("updates.automaticRecovery")}</p>}
          {review && !busy && !blocked && !done && !failed && !error && /\.dev\d+$/.test(review.plan.target_version) &&
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{t("updates.channel.previewWarning")}</p>}
          {review && !busy && !blocked && !done && review.plan.profiles.filter(p => p.restart).length > 1 &&
            <p className="mt-2 text-xs text-muted-foreground">{t("updates.sharedInstallation", { count: review.plan.profiles.filter(p => p.restart).length })}</p>}
        </div>
        {pendingId && recovery && !job?.recovery_active && ((delayed && !automaticRecovery) || needsRecovery) && <div className="mt-4 space-y-2 border-t pt-4">
          <p className="text-sm font-medium">{t("updates.recoveryTitle")}</p>
          <p className="text-xs leading-5 text-muted-foreground">{t("updates.recoveryDescription")}</p>
          <Textarea aria-label={t("updates.recoveryTitle")} readOnly value={recovery} rows={4}
            onFocus={event => event.currentTarget.select()}
            className="resize-none font-mono text-xs leading-5" />
        </div>}
        {guide && review ? <div className="min-h-0 overflow-y-auto overscroll-contain">
          <UpdateGuide key={`${token}:${review.plan.id}`} guide={guide} token={token} targetVersion={review.plan.target_version} />
          {ownerInstructions}
        </div> : blocked ? ownerInstructions : null}
        <div className={`mt-6 grid shrink-0 ${done || blocked ? "grid-cols-1" : "grid-cols-2"} gap-2.5`}>
          {!done && !blocked && <Button variant="secondary" onClick={close}>
            {t(done || failed || error || blocked ? "updates.close" : busy ? "updates.hide" : "updates.cancel")}
          </Button>}
          <Button variant="accent" className="min-w-0 whitespace-normal" disabled={!blocked && busy} aria-busy={busy}
            onClick={blocked ? close : primary}>
            {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />}
            {t(checkingStatus ? "settings.about.checking" : blocked ? "updates.close" : done ? "updates.return" : busy ? "updates.wait" : error ? "updates.checkAgain" : reviewAgain ? "updates.reviewAgain" : failed ? "updates.checkAgain" : "updates.apply")}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  </UpdateFlowContext.Provider>;
}

export function useUpdateFlow() { return useContext(UpdateFlowContext); }
