import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationsSettings } from "@/components/settings/IntegrationsSettings";
import { SettingsView } from "@/components/settings/SettingsView";
import type { IntegrationsPayload } from "@/lib/integrations";
import { ClientProvider } from "@/providers/ClientProvider";

const requestMutation = vi.fn();
const fetchMock = vi.fn();
const client = { requestMutation } as never;
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;

function fixture(): IntegrationsPayload {
  return {
    icloud: {
      username: "apple@example.com", timezone: "Europe/Warsaw", management_calendar: "Agent",
      sleep_hours: 8, default_wake_time: "07:00", morning_preparation_minutes: 30,
      briefing_minutes_after_wake: 15, auto_manage_sleep: false, credential_configured: true,
    },
    mail: {
      accounts: ["personal", "work"].map((id) => ({
        id, email: `${id}@example.com`, host: "imap.example.com", port: 993,
        username: id, allowed_folders: ["INBOX"], rules: [], credential_configured: true,
      })),
      dry_run: true, reconcile_interval_seconds: 300,
    },
    memory: { enabled: true, rerank_mode: "hybrid", items: null, status: "missing" },
    evolution: { enabled: false, mode: "shadow", capture_content: false, experiences: null, status: "stale" },
    services: [{ id: "mail", label: "Usługa pocztowa", state: "stopped", detail: "Nie uruchomiono usługi." }],
    notes: ["Dane lokalne, bez testu połączenia."], exported: false,
  };
}

function renderPanel(token = "initial-token") {
  return render(<ClientProvider client={client} token={token}><IntegrationsSettings /></ClientProvider>);
}
async function loaded() {
  await screen.findByRole("form", { name: "Konfiguracja iCloud" });
}
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  fetchMock.mockReset().mockResolvedValue(response(fixture()));
  requestMutation.mockReset().mockResolvedValue(fixture());
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Integrations settings", () => {
  it("renders loading, missing/stale status and null counters without inventing zeroes", async () => {
    renderPanel();
    expect(screen.getByText("Wczytywanie danych integracji…")).toBeInTheDocument();
    await loaded();
    const memory = within(screen.getByRole("region", { name: "Pamięć" }));
    const evolution = within(screen.getByRole("region", { name: "Evolution" }));
    expect(memory.getAllByText("Brak danych")).toHaveLength(2);
    expect(memory.queryByText("0")).not.toBeInTheDocument();
    expect(evolution.getByText("Dane nieaktualne")).toBeInTheDocument();
    expect(evolution.getByText("Brak danych")).toBeInTheDocument();
    expect(evolution.queryByText("0")).not.toBeInTheDocument();
    expect(screen.getByText("Zatrzymany")).toBeInTheDocument();
    expect(screen.getByText("Dane lokalne, bez testu połączenia.")).toBeInTheDocument();
    expect(screen.getByText(/Zapis konfiguracji nie uruchamia ani nie restartuje/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/integrations", expect.objectContaining({
      method: "GET", headers: { Authorization: "Bearer initial-token" }, cache: "no-store",
    }));
    expect(requestMutation).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /restart|test połączenia|wyślij|przenieś/i })).not.toBeInTheDocument();
  });

  it("shows empty accounts/services and distinguishes an actual zero from missing data", async () => {
    const data = fixture();
    data.mail.accounts = [];
    data.services = [];
    data.memory.items = 0;
    data.memory.status = null;
    fetchMock.mockResolvedValue(response(data));
    renderPanel();
    await loaded();
    expect(screen.getByText("Brak kont pocztowych. Dodaj pierwsze konto poniżej.")).toBeInTheDocument();
    expect(screen.getByText("Brak danych o usługach. Nie oznacza to, że są uruchomione.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Pamięć" })).getByText("0")).toBeInTheDocument();
    expect(screen.getByLabelText("Port IMAPS/TLS")).toHaveValue(993);
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
  });

  it("saves iCloud through WS only and omits a blank password to preserve the credential", async () => {
    renderPanel();
    await loaded();
    expect(screen.getByLabelText("Hasło aplikacji iCloud")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Hasło aplikacji iCloud")).toHaveValue("");
    change("Strefa czasowa", "UTC");
    const next = fixture();
    next.icloud.timezone = "UTC";
    requestMutation.mockResolvedValue(next);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    const { credential_configured: configured, ...fields } = next.icloud;
    expect(configured).toBe(true);
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.icloud", fields, 20_000);
    expect(requestMutation.mock.calls[0][1]).not.toHaveProperty("password");
    expect(screen.getByLabelText("Hasło aplikacji iCloud")).toHaveValue("");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears secrets immediately and on WS error without displaying, logging or persisting raw errors", async () => {
    const storage = vi.spyOn(localStorage, "setItem");
    const consoleError = vi.spyOn(console, "error");
    renderPanel();
    await loaded();
    const secret = "not-for-display-icloud";
    change("Hasło aplikacji iCloud", secret);
    requestMutation.mockRejectedValue(new Error(`Failed password=${secret}`));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
    expect(screen.getByLabelText("Hasło aplikacji iCloud")).toHaveValue("");
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać konfiguracji");
    expect(document.body).not.toHaveTextContent(secret);
    expect(consoleError).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.icloud", expect.objectContaining({ password: secret }), 20_000);
    requestMutation.mockResolvedValue(fixture());
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
    await waitFor(() => expect(requestMutation).toHaveBeenCalledTimes(2));
    expect(requestMutation.mock.calls[1][1]).not.toHaveProperty("password");
  });

  it("keeps separate multi-account drafts, clears secrets on selection, and saves one account/rules", async () => {
    renderPanel();
    await loaded();
    change("Serwer IMAP", "personal.example.com");
    change("Hasło aplikacji IMAP", "discard-on-switch");
    change("Konto pocztowe", "work");
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("imap.example.com");
    change("Konto pocztowe", "personal");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("personal.example.com");
    change("Konto pocztowe", "work");
    change("Dozwolone foldery (jeden w wierszu)", " INBOX \n\n Faktury\n");
    fireEvent.click(screen.getByRole("button", { name: "Dodaj regułę" }));
    change("Nazwa reguły", "Faktury");
    change("Folder docelowy", "Faktury");
    change("Nadawca / glob (jeden w wierszu)", "*@billing.example\n sender@example.com");
    change("Fragment tematu (jeden w wierszu)", "faktura\n invoice ");
    change("Hasło aplikacji IMAP", "mail-app-secret");
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację konta" }));
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.mail", {
      id: "work", email: "work@example.com", host: "imap.example.com", port: 993, username: "work",
      allowed_folders: ["INBOX", "Faktury"],
      rules: [{ name: "Faktury", destination: "Faktury", sender_globs: ["*@billing.example", "sender@example.com"], subject_contains: ["faktura", "invoice"] }],
      password: "mail-app-secret",
    }, 20_000);
    expect(screen.getByRole("option", { name: "personal@example.com (personal)" })).toBeInTheDocument();
    change("Konto pocztowe", "personal");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("personal.example.com");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves an existing mail credential when the password is whitespace-only", async () => {
    const data = fixture();
    data.mail.accounts[0].id = "constructor";
    fetchMock.mockResolvedValue(response(data));
    requestMutation.mockResolvedValue(data);
    renderPanel();
    await loaded();
    expect(screen.getByLabelText("Konto pocztowe")).toHaveValue("constructor");
    change("Hasło aplikacji IMAP", "   ");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację konta" }));
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(requestMutation.mock.calls[0][1]).not.toHaveProperty("password");
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
    expect(screen.getByText(/Hasło aplikacji jest zapisane/, { selector: "form[aria-label='Konfiguracja poczty IMAP'] p" })).toBeInTheDocument();
  });

  it("clears a successfully saved iCloud secret and ignores credentials returned outside the public contract", async () => {
    renderPanel();
    await loaded();
    change("Hasło aplikacji iCloud", "icloud-new-secret");
    requestMutation.mockResolvedValue({ ...fixture(), icloud: { ...fixture().icloud, password: "icloud-new-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(screen.getByLabelText("Hasło aplikacji iCloud")).toHaveValue("");
    expect(document.body).not.toHaveTextContent("icloud-new-secret");
    expect(requestMutation.mock.calls[0][1]).toHaveProperty("password", "icloud-new-secret");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("upserts a new account without replacing other accounts and omits blank mail passwords", async () => {
    renderPanel();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj nowe konto" }));
    change("Identyfikator konta", "third");
    change("Adres e-mail", "third@example.com");
    change("Serwer IMAP", "imap.third.example");
    change("Login IMAP", "third@example.com");
    const data = fixture();
    data.mail.accounts.push({ id: "third", email: "third@example.com", host: "imap.third.example", port: 993, username: "third@example.com", allowed_folders: ["INBOX"], rules: [], credential_configured: false });
    requestMutation.mockResolvedValue(data);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację konta" }));
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(requestMutation.mock.calls[0][0]).toBe("settings.integrations.mail");
    expect(requestMutation.mock.calls[0][1]).toEqual({ id: "third", email: "third@example.com", host: "imap.third.example", port: 993, username: "third@example.com", allowed_folders: ["INBOX"], rules: [] });
    expect(screen.getByLabelText("Konto pocztowe")).toHaveValue("third");
    expect(within(screen.getByLabelText("Konto pocztowe")).getAllByRole("option")).toHaveLength(4);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves dirty forms through refresh, including edits during fetch, and uses the current token", async () => {
    const view = renderPanel();
    await loaded();
    change("Kalendarz zarządzany", "Niezapisany kalendarz");
    change("Serwer IMAP", "unsaved.example.com");
    view.rerender(<ClientProvider client={client} token="fresh-token"><IntegrationsSettings /></ClientProvider>);
    let resolve!: (value: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
    fireEvent.click(screen.getByRole("button", { name: "Odśwież status" }));
    change("Kalendarz zarządzany", "Edycja w czasie odświeżania");
    const updated = fixture();
    updated.icloud.management_calendar = "Z serwera";
    updated.memory.items = 17;
    await act(async () => resolve(response(updated)));
    expect(screen.getByLabelText("Kalendarz zarządzany")).toHaveValue("Edycja w czasie odświeżania");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("unsaved.example.com");
    expect(within(screen.getByRole("region", { name: "Pamięć" })).getByText("17")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer fresh-token");
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("prepares saved consumer configurations through WS without testing or starting services", async () => {
    renderPanel();
    await loaded();
    change("Strefa czasowa", "Niezapisana strefa");
    const next = fixture();
    next.exported = true;
    next.message = "Pliki konfiguracji przygotowane lokalnie.";
    requestMutation.mockResolvedValue(next);
    fireEvent.click(screen.getByRole("button", { name: "Przygotuj konfiguracje usług" }));
    expect(await screen.findByText("Konfiguracje usług przygotowane. Usługi nie zostały uruchomione.")).toBeInTheDocument();
    expect(screen.getByText(next.message)).toBeInTheDocument();
    expect(screen.getByLabelText("Strefa czasowa")).toHaveValue("Niezapisana strefa");
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.prepare", {}, 20_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports a safe prepare error and does not perform any follow-up mutation", async () => {
    renderPanel();
    await loaded();
    requestMutation.mockRejectedValue(new Error("password=private-config-value"));
    fireEvent.click(screen.getByRole("button", { name: "Przygotuj konfiguracje usług" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się przygotować konfiguracji usług");
    expect(document.body).not.toHaveTextContent("private-config-value");
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Przygotuj konfiguracje usług" })).toBeEnabled();
  });

  it("handles initial and refresh failures safely, retains the last snapshot and allows retry", async () => {
    const body = vi.fn(async () => ({ error: "password=do-not-show" }));
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: body, text: body });
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych integracji");
    expect(body).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent("do-not-show");
    fireEvent.click(screen.getByRole("button", { name: "Odśwież status" }));
    await loaded();
    change("Serwer IMAP", "keep.example.com");
    fetchMock.mockRejectedValueOnce(new Error("password=do-not-show"));
    fireEvent.click(screen.getByRole("button", { name: "Odśwież status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Poprzednio pobrane dane mogą być nieaktualne");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("keep.example.com");
    expect(document.body).not.toHaveTextContent("do-not-show");
  });

  it("clears failed mail secrets, retains non-secret edits and safely handles malformed responses", async () => {
    renderPanel();
    await loaded();
    change("Serwer IMAP", "retry.example.com");
    change("Hasło aplikacji IMAP", "private-mail-password");
    requestMutation.mockResolvedValue({ error: "private-mail-password" });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację konta" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać konfiguracji");
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("retry.example.com");
    expect(document.body).not.toHaveTextContent("private-mail-password");
  });

  it("renders the integrations route independently of loading general settings and includes a sidebar link", async () => {
    fetchMock.mockImplementation((url: string) => url === "/api/settings/integrations"
      ? Promise.resolve(response(fixture()))
      : new Promise<Response>(() => {}));
    render(
      <ClientProvider client={client} token="tok">
        <SettingsView theme="light" initialSection="integrations" onToggleTheme={() => {}} onBackToChat={() => {}} onModelNameChange={() => {}} />
      </ClientProvider>,
    );
    await loaded();
    expect(screen.getByTestId("settings-section-transition")).toHaveAttribute("data-settings-section", "integrations");
    expect(screen.getByRole("button", { name: "Integracje" })).toHaveAttribute("aria-current", "page");
  });
});
