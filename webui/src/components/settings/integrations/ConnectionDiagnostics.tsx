import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ConnectionCheckRequest, ConnectionReport, IntegrationsPayload } from "@/lib/integrations";

const messages: Record<string, string> = {
  ok: "TLS i uwierzytelnienie poprawne (tylko odczyt).",
  not_configured: "Najpierw zapisz login i hasło aplikacji.",
  unknown_account: "Konto nie istnieje. Odśwież status.",
  blocked_target: "Adres usługi został zablokowany przez zabezpieczenia sieciowe.",
  authentication_failed: "Uwierzytelnienie odrzucone. Sprawdź login i hasło aplikacji.",
  tls_failed: "Nie udało się zweryfikować połączenia TLS.",
  timeout: "Przekroczono limit czasu testu.",
  busy: "Inny test jeszcze trwa. Spróbuj później.",
  connection_failed: "Nie udało się połączyć z usługą.",
  protocol_error: "Nieoczekiwana odpowiedź usługi.",
  redirect_refused: "Przekierowanie odrzucone — hasło nie zostało przekazane dalej.",
  credential_unavailable: "Zapisane hasło aplikacji jest niedostępne.",
};
const services: Record<string, string> = { imap: "IMAP", caldav: "CalDAV", icloud: "Apple", mail: "Poczta" };

export function ConnectionDiagnostics({ payload, busy, onCheck }: {
  payload: IntegrationsPayload;
  busy: boolean;
  onCheck: (request: ConnectionCheckRequest) => Promise<ConnectionReport>;
}) {
  const [result, setResult] = useState<{ label: string; report: ConnectionReport } | null>(null);
  const [failed, setFailed] = useState(false);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  // Saved account edits invalidate old diagnostic results; drafts are never submitted.
  useEffect(() => { setResult(null); setFailed(false); }, [payload]);
  const run = async (label: string, request: ConnectionCheckRequest) => {
    setResult(null); setFailed(false);
    try {
      const report = await onCheck(request);
      if (alive.current) setResult({ label, report });
    } catch {
      if (alive.current) setFailed(true);
    }
  };
  return <div className="space-y-3 p-4 sm:p-5">
    <p className="text-[13px] text-muted-foreground">Test używa wyłącznie zapisanych danych, nie szkiców. Sprawdza TLS i logowanie, bez zmiany kalendarzy lub wiadomości. Limit odpowiedzi: 12 sekund. Wynik nie oznacza ciągłego monitorowania.</p>
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" disabled={busy || !payload.icloud.credential_configured} onClick={() => void run("Apple", { target: "icloud" })}>Sprawdź połączenie Apple</Button>
      {payload.mail.accounts.filter((a) => a.managed_by !== "icloud").map((account) => <Button key={account.id} type="button" variant="outline" className="h-auto min-h-10 whitespace-normal break-all" disabled={busy || !account.credential_configured} onClick={() => void run(account.id, { target: "mail", account_id: account.id })}>Sprawdź IMAP: {account.id}</Button>)}
    </div>
    {failed ? <p role="alert" className="text-[13px] text-destructive">Nie udało się wykonać testu. Sprawdź połączenie z panelem.</p> : null}
    {result ? <div role="status" className="space-y-1 text-[13px]">
      <p className="font-medium">{result.label}: {result.report.ok ? "test poprawny" : "wymaga uwagi"}</p>
      {result.report.checks.map((check, index) => <p key={index}>{Object.hasOwn(services, check.service) ? services[check.service] : "Usługa"}: {Object.hasOwn(messages, check.code) ? messages[check.code] : "Nieznany wynik testu."}</p>)}
    </div> : null}
  </div>;
}
