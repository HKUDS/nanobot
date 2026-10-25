import { useEffect, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { copyTextToClipboard } from "@/lib/clipboard";
import { remoteAction } from "@/lib/remote-instances";
import { pairingReturnOrigin, type PairReturn } from "@/lib/remote-pair-return";
import type { ConnectionStatus } from "@/lib/types";
import { useRemoteConnections } from "./remote-context";
import { PairRouteSettings } from "./PairRouteSettings";
import { QuickPairSetupView, type PairInvitation, type PairConnectionPreview, type QuickPairPanel } from "./QuickPairSetupView";

/** Public invitation → encrypted receipt → explicit confirmation. No private key inputs. */
export function QuickPairSetup({ returned, active = true, onSSH, onClose }: { returned?: PairReturn | null; active?: boolean; onSSH: () => void; onClose: () => void }) {
  const { client } = useClient();
  const connections = useRemoteConnections();
  const [request, setRequest] = useState<PairInvitation | null>(returned ? { id: returned.id, command: "", expires: 0 } : null);
  const [preview, setPreview] = useState<PairConnectionPreview | null>(null);
  const [code, setCode] = useState(returned?.code || "");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyVisible, setBusyVisible] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  const [copied, setCopied] = useState(false);
  const [expired, setExpired] = useState(false);
  const [manual, setManual] = useState(false);
  const [panel, setPanel] = useState<QuickPairPanel>(null);
  const alive = useRef(true);
  const initialized = useRef(false);
  const requestId = useRef(returned?.id || "");
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
    const result = await remoteAction<PairInvitation>(client, "pair_start", { return_origin: pairingReturnOrigin() });
    if (!alive.current) { await remoteAction(client, "pair_cancel", { id: result.id }); return; }
    requestId.current = result.id;
    setRequest(result); setPreview(null); setCode(""); setCopied(false); setExpired(false); setManual(false); setPanel(null);
  });
  const review = () => run(async () => {
    if (!request) return;
    const result = await remoteAction<PairConnectionPreview>(client, "pair_preview", { id: request.id, code });
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
  return <QuickPairSetupView
    state={{ request, preview, code, saved: !!saved, busy, busyVisible, error, status, copied, expired, manual, panel, returned: !!returned }}
    routeSettings={saved ? <PairRouteSettings id={saved} /> : null}
    onStart={() => { void start(); }} onReview={() => { void review(); }} onConnect={() => { void connect(); }}
    onCopyCommand={copyCommand}
    onCodeChange={(value) => { setCode(value); setError(""); }}
    onManualChange={(value) => { setManual(value); setPanel(null); setError(""); }} onPanelChange={setPanel}
    onBack={() => { setPreview(null); setError(""); if (!request?.command) setManual(true); }}
    onCancel={() => { connections?.cancel(); onClose(); }} onSSH={onSSH} />;
}
