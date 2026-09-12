import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ConnectionDiagnostics } from "@/components/settings/integrations/ConnectionDiagnostics";
import { ConnectionSlotForm } from "@/components/settings/integrations/ConnectionSlotForm";
import { IcloudIntegrationForm, MailIntegrationForm } from "@/components/settings/integrations/IntegrationForms";
import { ReadOnlyRow, SettingsGroup, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import {
  checkIntegration,
  type ConnectionCheckRequest,
  fetchIntegrations,
  prepareIntegrations,
  saveIcloudIntegration,
  saveConnectionSlot,
  type ConnectionSlotName,
  saveMailIntegration,
  type IntegrationsPayload,
} from "@/lib/integrations";
import { useClient } from "@/providers/ClientProvider";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="min-w-0">
      <SettingsSectionTitle>{title}</SettingsSectionTitle>
      <SettingsGroup>{children}</SettingsGroup>
    </section>
  );
}

const STATUS_LABELS: Record<string, string> = {
  ok: "Dostępny", ready: "Gotowy", running: "Działa", active: "Aktywny",
  stopped: "Zatrzymany", inactive: "Nieaktywny", disabled: "Wyłączony",
  missing: "Brak danych", unavailable: "Niedostępny", unknown: "Brak danych",
  stale: "Dane nieaktualne", error: "Błąd", failed: "Błąd", configured: "Skonfigurowany",
  not_configured: "Nieskonfigurowany", not_running: "Nie działa",
  responding: "Odpowiada", index_available: "Indeks dostępny",
  observations_available: "Obserwacje dostępne", no_data: "Brak danych",
  log_over_read_limit: "Log przekracza limit odczytu",
  activating: "Uruchamianie", deactivating: "Zatrzymywanie",
};

export function IntegrationsSettings() {
  const { client, getToken } = useClient();
  const { t } = useTranslation();
  const tx = (key: string, defaultValue: string) => t(`settings.integrations.${key}`, { defaultValue });
  const [payload, setPayload] = useState<IntegrationsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<"icloud" | "mail" | "prepare" | "check" | ConnectionSlotName | null>(null);
  const [error, setError] = useState<"load" | "save" | "prepare" | null>(null);
  const [success, setSuccess] = useState<"saved" | "prepared" | "refreshed" | null>(null);
  const [prepareMessage, setPrepareMessage] = useState<string | null>(null);
  const requestId = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const mutationPending = useRef(false);

  const refresh = useCallback(async () => {
    if (mutationPending.current) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setPrepareMessage(null);
    try {
      const next = await fetchIntegrations(getToken(), controller.signal);
      if (mounted.current && id === requestId.current) {
        setPayload(next);
        setSuccess("refreshed");
      }
    } catch {
      // Never render exception messages: gateways/proxies can echo credentials.
      if (mounted.current && id === requestId.current) setError("load");
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      requestId.current += 1;
      abort.current?.abort();
    };
  }, [refresh]);

  const mutate = async (
    kind: "icloud" | "mail" | "prepare" | ConnectionSlotName,
    operation: () => Promise<IntegrationsPayload>,
  ): Promise<boolean> => {
    if (mutationPending.current || loading) return false;
    mutationPending.current = true;
    setAction(kind);
    setError(null);
    setSuccess(null);
    setPrepareMessage(null);
    try {
      const next = await operation();
      if (!mounted.current) return false;
      setPayload(next);
      setSuccess(kind === "prepare" ? "prepared" : "saved");
      if (kind === "prepare") setPrepareMessage(next.message ?? null);
      return true;
    } catch {
      if (mounted.current) setError(kind === "prepare" ? "prepare" : "save");
      return false;
    } finally {
      mutationPending.current = false;
      if (mounted.current) setAction(null);
    }
  };

  const check = async (request: ConnectionCheckRequest) => {
    if (mutationPending.current || loading) throw new Error("Busy");
    mutationPending.current = true;
    setAction("check");
    try {
      return await checkIntegration(client, request);
    } finally {
      mutationPending.current = false;
      if (mounted.current) setAction(null);
    }
  };

  const noData = tx("noData", "Brak danych");
  const stateLabel = (value: string | null) => value
    ? tx(`state.${value}`, Object.hasOwn(STATUS_LABELS, value) ? STATUS_LABELS[value] : "Nieznany stan")
    : noData;
  const yesNo = (value: boolean) => value ? tx("yes", "Tak") : tx("no", "Nie");
  const errorMessage = error === "load"
    ? tx("error.load", "Nie udało się pobrać danych integracji. Spróbuj odświeżyć. Poprzednio pobrane dane mogą być nieaktualne.")
    : error === "prepare"
      ? tx("error.prepare", "Nie udało się przygotować konfiguracji usług. Sprawdź ustawienia i spróbuj ponownie.")
      : tx("error.save", "Nie udało się zapisać konfiguracji. Sprawdź pola i połączenie z panelem, a następnie spróbuj ponownie. Jeśli zmieniasz hasło, wpisz je ponownie.");

  return (
    <div className="space-y-6">
      <Card title={tx("status.title", "Status integracji")}>
        <div className="space-y-3 p-4 sm:p-5">
          <p className="text-[13px] leading-6 text-muted-foreground">
            {tx("status.description", "Zapis konfiguracji nie uruchamia ani nie restartuje usług i nie testuje połączenia. Ten panel nie wysyła, nie przenosi ani nie usuwa wiadomości. Statusy pochodzą z ostatnio dostępnych danych.")}
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button type="button" variant="outline" disabled={loading || action !== null} onClick={() => void refresh()}>
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <RefreshCw className="mr-2 h-4 w-4" aria-hidden />}
              {tx("refresh", "Odśwież status")}
            </Button>
            <Button type="button" className="h-auto min-h-10 whitespace-normal" disabled={!payload || loading || action !== null} onClick={() => void mutate("prepare", () => prepareIntegrations(client))}>
              {tx("prepare", "Przygotuj konfiguracje usług")}
            </Button>
          </div>
          <p className="text-[12px] leading-5 text-muted-foreground">
            {tx("prepareHint", "Przygotowanie tworzy pliki konfiguracji dla usług z zapisanych ustawień, bez ich uruchamiania. Najpierw zapisz zmiany w formularzach. Odświeżanie nie nadpisuje niezapisanych pól.")}
          </p>
          {loading ? <p role="status" className="text-[13px]">{tx("loading", "Wczytywanie danych integracji…")}</p> : null}
          {action ? <p role="status" className="text-[13px]">{action === "check" ? "Sprawdzanie połączenia…" : tx("saving", "Zapisywanie konfiguracji…")}</p> : null}
          {error ? <p role="alert" className="text-[13px] text-destructive">{errorMessage}</p> : null}
          {success ? (
            <p role="status" className="text-[13px] text-muted-foreground">
              {success === "saved"
                ? tx("success.saved", "Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.")
                : success === "prepared"
                  ? tx("success.prepared", "Konfiguracje usług przygotowane. Usługi nie zostały uruchomione.")
                  : tx("success.refreshed", "Dane odświeżone. Nie wykonano testu połączenia.")}
            </p>
          ) : null}
          {prepareMessage ? <p className="break-words text-[13px] text-muted-foreground">{prepareMessage}</p> : null}
        </div>
        {payload ? (
          <>
            <ReadOnlyRow title={tx("exported", "Przygotowano konfiguracje usług")} value={yesNo(payload.exported)} />
            <ReadOnlyRow title={tx("dryRun", "Poczta: tryb próbny (dry-run)")} value={tx("dryRunValue", "Zawsze włączony — bez zmian w skrzynce")} />
            <ReadOnlyRow title={tx("interval", "Interwał uzgadniania poczty (sekundy)")} value={String(payload.mail.reconcile_interval_seconds)} />
            {payload.notes.length > 0 ? (
              <ul className="list-inside list-disc space-y-1 break-words p-4 text-[13px] text-muted-foreground sm:p-5">
                {payload.notes.map((note, index) => <li key={index}>{note}</li>)}
              </ul>
            ) : null}
          </>
        ) : null}
      </Card>

      {payload ? (
        <>
          <div className="grid min-w-0 gap-6 xl:grid-cols-2">
            <Card title={tx("memory.title", "Pamięć")}>
              <ReadOnlyRow title={tx("configuredEnabled", "Włączona w konfiguracji")} value={yesNo(payload.memory.enabled)} />
              <ReadOnlyRow title={tx("state", "Stan danych")} value={stateLabel(payload.memory.status)} />
              <ReadOnlyRow title={tx("memory.items", "Liczba elementów")} value={payload.memory.items === null ? noData : String(payload.memory.items)} />
              <ReadOnlyRow title={tx("memory.rerank", "Tryb rerankingu")} value={payload.memory.rerank_mode || noData} />
            </Card>
            <Card title={tx("evolution.title", "Evolution")}>
              <ReadOnlyRow title={tx("configuredEnabled", "Włączona w konfiguracji")} value={yesNo(payload.evolution.enabled)} />
              <ReadOnlyRow title={tx("state", "Stan danych")} value={stateLabel(payload.evolution.status)} />
              <ReadOnlyRow title={tx("evolution.experiences", "Liczba doświadczeń")} value={payload.evolution.experiences === null ? noData : String(payload.evolution.experiences)} />
              <ReadOnlyRow title={tx("evolution.mode", "Tryb")} value={payload.evolution.mode || noData} />
              <ReadOnlyRow title={tx("evolution.capture", "Zapisywanie treści")} value={yesNo(payload.evolution.capture_content)} />
            </Card>
          </div>
          <Card title={tx("services.title", "Usługi")}>
            {payload.services.length === 0 ? (
              <p className="p-4 text-[13px] text-muted-foreground sm:p-5">{tx("services.empty", "Brak danych o usługach. Nie oznacza to, że są uruchomione.")}</p>
            ) : payload.services.map((service) => (
              <ReadOnlyRow key={service.id} title={service.label} value={stateLabel(service.state)} description={service.detail} />
            ))}
          </Card>
          <Card title="Diagnostyka połączeń">
            <ConnectionDiagnostics payload={payload} busy={loading || action !== null} onCheck={check} />
          </Card>
          <Card title={tx("icloud.accountTitle", "Apple — kalendarz i poczta iCloud")}>
            <IcloudIntegrationForm config={payload.icloud} busy={action !== null} refreshing={loading} onSave={(value) => mutate("icloud", () => saveIcloudIntegration(client, value))} />
          </Card>
          {payload.connection_slots ? (
            <div className="grid min-w-0 gap-6 xl:grid-cols-2">
              {(["motis", "firefly_iii"] as const).map((name) => {
                const title = name === "motis" ? "MOTIS" : "Firefly III";
                return <Card key={name} title={title}>
                  <ConnectionSlotForm title={title} config={payload.connection_slots![name]}
                    busy={action !== null || loading}
                    onSave={(value) => mutate(name, () => saveConnectionSlot(client, name, value))} />
                </Card>;
              })}
            </div>
          ) : null}
          <Card title={tx("mail.title", "Poczta — konta IMAP")}>
            <MailIntegrationForm accounts={payload.mail.accounts} busy={action !== null} refreshing={loading} onSave={(value) => mutate("mail", () => saveMailIntegration(client, value))} />
          </Card>
        </>
      ) : null}
    </div>
  );
}
