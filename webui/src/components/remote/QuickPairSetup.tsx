import { useEffect, useId, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, Check, ChevronDown, Copy, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Disclosure, DisclosureContent } from "@/components/ui/disclosure";
import { Textarea } from "@/components/ui/textarea";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useClient } from "@/providers/ClientProvider";
import { copyTextToClipboard } from "@/lib/clipboard";
import { CodeBlock } from "@/components/CodeBlock";
import { remoteAction } from "@/lib/remote-instances";
import { pairingReturnOrigin, type PairReturn } from "@/lib/remote-pair-return";
import type { ConnectionStatus } from "@/lib/types";
import { useRemoteConnections } from "./RemoteInstances";
import { PairRouteSettings } from "./PairRouteSettings";
import "./remote-layout.css";

type Request = { id: string; command: string; expires: number };
type Preview = { id: string; host: string; hostname: string; fingerprint: string; authorized_until: number; revoke_command: string;
  existing_connection?: { id: string; name: string; connected: boolean } };

/** Public invitation → encrypted receipt → explicit confirmation. No private key inputs. */
export function QuickPairSetup({ returned, active = true, onSSH, onClose }: { returned?: PairReturn | null; active?: boolean; onSSH: () => void; onClose: () => void }) {
  const { t } = useTranslation();
  const { client } = useClient();
  const connections = useRemoteConnections();
  const [request, setRequest] = useState<Request | null>(returned ? { id: returned.id, command: "", expires: 0 } : null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [code, setCode] = useState(returned?.code || "");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyVisible, setBusyVisible] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  const [copied, setCopied] = useState(false);
  const [expired, setExpired] = useState(false);
  const [manual, setManual] = useState(false);
  const [panel, setPanel] = useState<"command" | "help" | null>(null);
  const alive = useRef(true);
  const initialized = useRef(false);
  const requestId = useRef(returned?.id || "");
  const manualInput = useRef<HTMLTextAreaElement>(null);
  const focusManual = useRef(false);
  const codeId = useId();
  const panelId = useId();
  const waitingForLocal = status !== "open";
  const pending = busy || (waitingForLocal && !error);

  useEffect(() => client.onStatus(setStatus), [client]);

  useEffect(() => {
    if (!pending) { setBusyVisible(false); return; }
    // Fast local preparation should not flash a loading label or move the dialog.
    const timer = window.setTimeout(() => setBusyVisible(true), 200);
    return () => window.clearTimeout(timer);
  }, [pending]);

  useEffect(() => {
    alive.current = active;
    return () => {
      alive.current = false;
      // A link opens in a new tab. Closing/reloading the originating page must
      // not destroy its key before the new page can validate the receipt.
      // Pending invitations are bounded and expire in PairStore.
    };
  }, [client, active]);
  useEffect(() => {
    if (!request?.expires || saved) return;
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, request.expires * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [request, saved]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); }
    catch (reason) {
      const localFailure = reason instanceof Error && "status" in reason && [503, 504].includes(Number(reason.status));
      if (alive.current) {
        const code = localFailure ? "local_connection_unavailable" : reason instanceof Error ? reason.message : "unknown";
        setError(`remote.errors.${code}`);
      }
    } finally { if (alive.current) setBusy(false); }
  };
  const start = () => run(async () => {
    if (requestId.current) await remoteAction(client, "pair_cancel", { id: requestId.current });
    const result = await remoteAction<Request>(client, "pair_start", { return_origin: pairingReturnOrigin() });
    if (!alive.current) { await remoteAction(client, "pair_cancel", { id: result.id }); return; }
    requestId.current = result.id;
    setRequest(result); setPreview(null); setCode(""); setCopied(false); setExpired(false); setManual(false); setPanel(null);
  });
  const review = () => run(async () => {
    if (!request) return;
    const result = await remoteAction<Preview>(client, "pair_preview", { id: request.id, code });
    if (alive.current) setPreview(result);
  });
  const connect = () => run(async () => {
    if (!request || !preview || !connections) return;
    let id = saved;
    if (!id) {
      const result = await remoteAction<{ id: string }>(client, "pair_finish", { id: request.id, code });
      id = result.id;
      if (!alive.current) return;
      setSaved(id);
    }
    await connections.refresh();
    if (!alive.current) return;
    await connections.connect(id, () => alive.current);
    if (alive.current) onClose();
  });

  useEffect(() => {
    if (!active || initialized.current) return;
    // A return link mounts immediately after bootstrap, before the local socket
    // opens. Wait for it; rejecting here would mislabel a valid link as invalid.
    if (status !== "open") {
      const timer = window.setTimeout(() => setError("remote.errors.local_connection_unavailable"), 10_000);
      return () => window.clearTimeout(timer);
    }
    initialized.current = true;
    if (returned) void review();
    else void start();
    // One invitation per mounted dialog, never one per re-render. The returned
    // receipt is reviewed only; saving/connecting still requires a user click.
  }, [status, active]);
  const copyCommand = () => {
    if (!request) return;
    void copyTextToClipboard(request.command).then((ok) => {
      if (!alive.current || requestId.current !== request.id || Date.now() >= request.expires * 1000) return;
      if (ok) { setCopied(true); setError(""); setPanel(null); }
      else { setPanel("command"); setError("remote.pair.copyFailed"); }
    });
  };
  const invalidReturn = ["pair_invalid", "pair_expired", "pair_used"].some((code) => error === `remote.errors.${code}`);
  const requestUnavailable = error === "remote.errors.pair_expired" || error === "remote.errors.pair_used";
  const restartAvailable = !saved && (expired || requestUnavailable || (!!error && !request?.command && !preview && (!returned || invalidReturn)));
  const visiblePreview = restartAvailable ? null : preview;
  const reviewingReturn = !!returned && !request?.command && !visiblePreview && !manual && !restartAvailable;
  const title = visiblePreview ? visiblePreview.existing_connection ? "remote.sameInstance.title" : "remote.pair.confirmTitle" : reviewingReturn ? "remote.pair.review" : restartAvailable ? "remote.add"
    : manual ? "remote.pair.code" : copied ? "remote.pair.copiedTitle" : "remote.add";
  const description = visiblePreview || reviewingReturn ? "remote.pair.confirmLinkDescription" : restartAvailable ? "remote.pair.introHint"
    : manual ? "remote.pair.codeHint" : copied ? "remote.pair.afterCopyHint" : "remote.pair.introHint";
  const showCopied = copied && !manual && !visiblePreview && !restartAvailable;
  const showIllustration = !visiblePreview && !manual && !reviewingReturn && !restartAvailable;
  const showBusy = pending && busyVisible;
  const actionLabel = restartAvailable ? "remote.pair.restart" : reviewingReturn ? error ? "remote.retry" : "remote.pair.review" : visiblePreview ? saved ? "remote.retry" : visiblePreview.existing_connection ? "remote.sameInstance.saveAndOpen" : "remote.connect"
    : manual ? "remote.pair.review" : copied ? "remote.pair.copyAgain" : "remote.pair.copy";
  const busyLabel = waitingForLocal ? "remote.pair.waitingForLocal" : visiblePreview ? "remote.connecting" : !restartAvailable && (manual || returned)
    ? "remote.pair.checkingLink" : "remote.pair.preparing";

  return <div className="remote-pair flex min-h-0 flex-col">
    <div className="-mx-1 min-h-0 overflow-y-auto overscroll-contain px-1">
      <DialogHeader className={showIllustration ? "space-y-0 text-center sm:text-center" : "pr-5 text-left"}>
        {showIllustration && <RemoteConnectionIllustration />}
        <div aria-live="polite" aria-atomic="true" className="space-y-1.5">
          <DialogTitle className={showIllustration ? "flex min-h-5 items-center justify-center gap-2 text-xl leading-snug tracking-normal" : "flex min-h-5 items-center gap-2"}>
            {showCopied && <Check aria-hidden="true" className="h-5 w-5 shrink-0 motion-safe:animate-in motion-safe:fade-in duration-150" />}
            <span className="min-w-0 [overflow-wrap:anywhere]">{t(title)}</span>
          </DialogTitle>
          <DialogDescription>{t(description)}</DialogDescription>
        </div>
      </DialogHeader>
      {visiblePreview ? <div className="space-y-4 pt-4">
        <div className="rounded-2xl bg-muted/50 p-4">
          <p className="font-medium [overflow-wrap:anywhere]">{visiblePreview.existing_connection?.name || visiblePreview.hostname}</p>
          <p className="mt-1 break-all text-xs text-muted-foreground">{visiblePreview.host}</p>
        </div>
        {visiblePreview.existing_connection && <p role="status" className="text-xs leading-5 text-muted-foreground">{t("remote.sameInstance.pairHint")}</p>}
        <p className="text-[13px] leading-5">{t("remote.pair.access")}</p>
        <p className="text-xs leading-5 text-muted-foreground">{t("remote.pair.expiry", { date: new Date(visiblePreview.authorized_until * 1000).toLocaleDateString() })}</p>
        <Disclosure className="text-xs text-muted-foreground" summaryClassName="flex min-h-9 items-center gap-2 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          summary={<><ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" />{t("remote.pair.security")}</>}>
          <p className="my-2 leading-5">{t("remote.pair.fingerprint")}</p><code className="block break-all">{visiblePreview.fingerprint}</code>
          <p className="mb-2 mt-4 leading-5">{t("remote.pair.revoke")}</p><CodeBlock language="bash" code={visiblePreview.revoke_command} highlight={false} className="min-w-0 [&_pre]:[overflow-wrap:anywhere]" />
        </Disclosure>
        {saved && error && <div className="space-y-2"><p className="text-xs leading-5 text-muted-foreground">{t("remote.pair.retryHint")}</p>
          <Disclosure summaryClassName="flex min-h-9 items-center gap-2 rounded-xl text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" contentClassName="pt-2"
            summary={<><ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" />{t("remote.pair.route")}</>}><PairRouteSettings id={saved} /></Disclosure>
        </div>}
      </div> : restartAvailable ? null : <>
        {manual && <div className="space-y-2 pt-4"><label htmlFor={codeId} className="sr-only">{t("remote.pair.code")}</label>
          <Textarea ref={manualInput} id={codeId} value={code} onChange={(event) => { setCode(event.target.value); setError(""); }} placeholder="nbpc1.…" autoComplete="off" spellCheck={false} disabled={busy || expired} className="min-h-20 resize-none break-all font-mono text-xs" />
        </div>}
        <div>
          <DisclosureContent id={panelId} open={panel === "command" && !!request?.command} className="pt-4">
            <div className="rounded-2xl bg-muted/50 p-3">
              <code className="block max-h-32 select-text overflow-y-auto text-[11px] leading-5 [overflow-wrap:anywhere]" aria-label={t("remote.pair.command")}>{request?.command}</code>
            </div>
          </DisclosureContent>
          <DisclosureContent open={panel === "help"} className="pt-4">
            <div className="space-y-2 rounded-2xl bg-muted/50 p-3 text-xs leading-5 text-muted-foreground">
              <p className="font-medium text-foreground">{t("remote.pair.helpTitle")}</p>
              <p>{t("remote.pair.requirements")}</p>
              <p>{t("remote.pair.runHint")}</p>
              <p>{t("remote.pair.validityHint")}</p>
            </div>
          </DisclosureContent>
        </div>
      </>}
      {expired && !saved && <p role="status" className="mt-4 text-xs leading-5 text-muted-foreground">{t("remote.pair.expired")}</p>}
      {error && <p role="alert" className="remote-alert mt-4 items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{t(error, { defaultValue: t("remote.errors.unknown") })}</span></p>}
    </div>
    <div className={visiblePreview ? "remote-dialog-actions shrink-0 pt-5" : "flex shrink-0 flex-col gap-2 pt-5"}>
      {visiblePreview && (!saved ? <Button className="remote-action" variant="ghost" disabled={busy} onClick={() => { setPreview(null); setError(""); if (!request?.command) setManual(true); }}><ArrowLeft className="mr-1 h-4 w-4" />{t("remote.back")}</Button>
          : <Button className="remote-action" variant="ghost" onClick={() => { connections?.cancel(); onClose(); }}>{t("common.cancel")}</Button>
      )}
      <Button variant={showCopied ? "outline" : "default"} className={showCopied ? "remote-action bg-transparent" : "remote-action"} aria-label={t(showBusy ? busyLabel : actionLabel)} aria-busy={pending} disabled={busy || waitingForLocal || (!restartAvailable && (!request || (!visiblePreview && (manual || reviewingReturn ? !code.trim() : !request.command))))} onClick={() => { if (restartAvailable) void start(); else if (visiblePreview) void connect(); else if (manual || reviewingReturn) void review(); else copyCommand(); }}>
        {showBusy ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" /> : !restartAvailable && !visiblePreview && !manual && !reviewingReturn ? <Copy aria-hidden="true" className="mr-2 h-4 w-4 shrink-0" /> : null}
        <span role="status" className="min-w-0">{t(showBusy ? busyLabel : actionLabel)}</span>
      </Button>
      {!visiblePreview && <div className="remote-pair-alternatives -mx-3 gap-1">
        {!restartAvailable && request?.command ? manual ? <Button className="remote-action" variant="ghost" size="sm" disabled={busy} onClick={() => { setManual(false); setPanel(null); setError(""); }}>{t("remote.back")}</Button>
          : <Button variant="ghost" size="sm" className="remote-action justify-start text-left text-xs text-muted-foreground" disabled={expired} aria-expanded={panel === "command"} aria-controls={panelId} onClick={() => setPanel(panel === "command" ? null : "command")}>{t("remote.pair.showCommand")}</Button> : <span />}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="sm" className="remote-action justify-end text-right text-xs text-muted-foreground">{t("remote.pair.otherWays")}<ChevronDown aria-hidden="true" className="ml-1 h-3.5 w-3.5 shrink-0" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" onCloseAutoFocus={(event) => {
            if (focusManual.current) { event.preventDefault(); focusManual.current = false; manualInput.current?.focus(); }
          }}>
            <DropdownMenuItem disabled={!request || busy || expired || restartAvailable} onSelect={() => { focusManual.current = true; setManual(true); setPanel(null); setError(""); }}>{t("remote.pair.pasteInstead")}</DropdownMenuItem>
            <DropdownMenuItem onSelect={onSSH}>{t("remote.pair.useSSH")}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled={restartAvailable} onSelect={() => setPanel(panel === "help" ? null : "help")}>{t("remote.pair.helpTitle")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>}
    </div>
  </div>;
}

/** Decorative overview, not a live connection-status indicator. */
function RemoteConnectionIllustration() {
  return <svg viewBox="0 0 208 88" width="184" height="78" aria-hidden="true" focusable="false" className="mx-auto mb-4 shrink-0 text-foreground/70" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M78 51 C111 65 114 28 146 36" className="text-muted-foreground/50" strokeWidth="2.5" />
    <rect x="10" y="25" width="68" height="43" rx="3" />
    <path d="M4 68 H84 V70 A5 5 0 0 1 79 75 H9 A5 5 0 0 1 4 70 Z" />
    <g className="text-muted-foreground">
      <rect x="27" y="34" width="34" height="26" rx="2" />
      <path d="M32 39 h.01 M36 39 h.01 M40 39 h.01" strokeWidth="2.5" />
    </g>
    <rect x="146" y="10" width="50" height="70" rx="3" />
    <image href="/brand/nanobot_mark.svg" x="155" y="17" width="32" height="32" />
    <path d="M146 53 H196 M146 66 H196 M152 60 H177 M152 73 H177 M152 80 V83 H158 V80 M184 80 V83 H190 V80" />
    <circle cx="188" cy="60" r="1.8" />
    <circle cx="188" cy="73" r="1.8" />
  </svg>;
}
