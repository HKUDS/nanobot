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
    connection_slots: {
      motis: { enabled: false, base_url: "", read_only: true, credential_configured: false, status: "adapter_not_installed" },
      firefly_iii: { enabled: false, base_url: "", read_only: true, credential_configured: false, status: "adapter_not_installed" },
    },
    icloud: {
      username: "apple@example.com", timezone: "Europe/Warsaw", management_calendar: "Agent",
      sleep_hours: 8, default_wake_time: "07:00", morning_preparation_minutes: 30,
      briefing_minutes_after_wake: 15, auto_manage_sleep: false, credential_configured: true,
    },
    mail: {
      accounts: ["personal", "work"].map((id) => ({
        id, email: `${id}@example.com`, host: "imap.example.com", port: 993,
        username: id, allowed_folders: [], folder_policy: "all" as const, rules: [], credential_configured: true,
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
    change("Apple ID (e-mail)", "changed@example.com");
    const next = fixture();
    next.icloud.username = "changed@example.com";
    requestMutation.mockResolvedValue(next);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(next.icloud.credential_configured).toBe(true);
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.icloud", { username: "changed@example.com" }, 20_000);
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

  it("keeps separate multi-account drafts and saves one account without changing folder policy or rules", async () => {
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
    expect(screen.queryByLabelText(/Dozwolone foldery/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj regułę" })).not.toBeInTheDocument();
    expect(screen.getByText(/Wszystkie foldery są dostępne/)).toBeInTheDocument();
    change("Hasło aplikacji IMAP", "mail-app-secret");
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację konta" }));
    expect(screen.getByLabelText("Hasło aplikacji IMAP")).toHaveValue("");
    await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.mail", {
      id: "work", email: "work@example.com", host: "imap.example.com", port: 993, username: "work",
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
    expect(requestMutation.mock.calls[0][1]).toEqual({ id: "third", email: "third@example.com", host: "imap.third.example", port: 993, username: "third@example.com" });
    expect(screen.getByLabelText("Konto pocztowe")).toHaveValue("third");
    expect(within(screen.getByLabelText("Konto pocztowe")).getAllByRole("option")).toHaveLength(4);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves dirty forms through refresh, including edits during fetch, and uses the current token", async () => {
    const view = renderPanel();
    await loaded();
    change("Apple ID (e-mail)", "unsaved@example.com");
    change("Serwer IMAP", "unsaved.example.com");
    view.rerender(<ClientProvider client={client} token="fresh-token"><IntegrationsSettings /></ClientProvider>);
    let resolve!: (value: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
    fireEvent.click(screen.getByRole("button", { name: "Odśwież status" }));
    change("Apple ID (e-mail)", "editing@example.com");
    const updated = fixture();
    updated.icloud.username = "server@example.com";
    updated.memory.items = 17;
    await act(async () => resolve(response(updated)));
    expect(screen.getByLabelText("Apple ID (e-mail)")).toHaveValue("editing@example.com");
    expect(screen.getByLabelText("Serwer IMAP")).toHaveValue("unsaved.example.com");
    expect(within(screen.getByRole("region", { name: "Pamięć" })).getByText("17")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer fresh-token");
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("prepares saved consumer configurations through WS without testing or starting services", async () => {
    renderPanel();
    await loaded();
    change("Apple ID (e-mail)", "unsaved@example.com");
    const next = fixture();
    next.exported = true;
    next.message = "Pliki konfiguracji przygotowane lokalnie.";
    requestMutation.mockResolvedValue(next);
    fireEvent.click(screen.getByRole("button", { name: "Przygotuj konfiguracje usług" }));
    expect(await screen.findByText("Konfiguracje usług przygotowane. Usługi nie zostały uruchomione.")).toBeInTheDocument();
    expect(screen.getByText(next.message)).toBeInTheDocument();
    expect(screen.getByLabelText("Apple ID (e-mail)")).toHaveValue("unsaved@example.com");
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


it("saves inert integration slots over WS and clears tokens even on failure", async () => {
  renderPanel();
  await loaded();
  const secret = "private-firefly-token";
  change("Adres Firefly III", "https://finance.example.org");
  change("Token Firefly III (opcjonalny)", secret);
  requestMutation.mockRejectedValue(new Error(secret));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz miejsce Firefly III" }));
  expect(screen.getByLabelText("Token Firefly III (opcjonalny)")).toHaveValue("");
  await screen.findByRole("alert");
  expect(requestMutation).toHaveBeenCalledWith("settings.integrations.firefly_iii", {
    base_url: "https://finance.example.org", password: secret,
  }, 20_000);
  expect(document.body).not.toHaveTextContent(secret);
  expect(screen.getByRole("form", { name: "Konfiguracja MOTIS" })).toHaveTextContent("adapter nie jest jeszcze zainstalowany");
});


it("shows exactly email and password for Apple and guards unsaved edits on browser exit", async () => {
  renderPanel();
  await loaded();
  const form = screen.getByRole("form", { name: "Konfiguracja iCloud" });
  expect(form.querySelectorAll("input")).toHaveLength(2);
  expect(within(form).queryByLabelText(/pobud|snu|Strefa|Kalendarz zarządzany/i)).not.toBeInTheDocument();
  const clean = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
  change("Apple ID (e-mail)", "changed@example.com");
  const dirty = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirty);
  expect(dirty.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
  await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
  const saved = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(saved);
  expect(saved.defaultPrevented).toBe(false);
});

it("reuses the linked Apple account and sends edits to the single Apple form", async () => {
  const initial = fixture();
  initial.mail.accounts = [];
  fetchMock.mockResolvedValue(response(initial));
  renderPanel();
  await loaded();
  const next = fixture();
  next.mail.accounts = [{ id: "icloud", email: "apple@example.com", username: "apple@example.com", host: "imap.mail.me.com", port: 993, allowed_folders: [], folder_policy: "all", managed_by: "icloud", rules: [], credential_configured: true }];
  requestMutation.mockResolvedValue(next);
  fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację iCloud" }));
  await screen.findByText("Konfiguracja zapisana. Nie uruchomiono usług ani nie przetestowano połączenia.");
  expect(screen.getByLabelText("Konto pocztowe")).toHaveValue("icloud");
  expect(screen.getByLabelText("Serwer IMAP")).toBeDisabled();
  expect(screen.getByLabelText("Hasło aplikacji IMAP")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Zapisz konfigurację konta" })).toBeDisabled();
  const scroll = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
  fireEvent.click(screen.getByRole("button", { name: "Edytuj konto Apple" }));
  expect(scroll).toHaveBeenCalled();
  expect(screen.getByLabelText("Apple ID (e-mail)")).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Dodaj nowe konto" }));
  expect(screen.getByLabelText("Serwer IMAP")).toBeEnabled();
  expect(requestMutation).toHaveBeenCalledTimes(1);
});

describe("read-only connection diagnostics", () => {
  it("checks saved Apple credentials explicitly without transmitting form drafts or rendering raw diagnostics", async () => {
    renderPanel();
    await loaded();
    change("Hasło aplikacji iCloud", "unsaved-private-value");
    change("Apple ID (e-mail)", "draft@example.org");
    requestMutation.mockResolvedValue({ ok: false, read_only: true, checks: [
      { service: "imap", ok: false, code: "authentication_failed", message: "private-backend-error" },
    ] });
    fireEvent.click(screen.getByRole("button", { name: "Sprawdź połączenie Apple" }));
    await screen.findByText(/IMAP: Uwierzytelnienie odrzucone/);
    expect(requestMutation).toHaveBeenCalledWith("settings.integrations.check", { target: "icloud" }, 20_000);
    expect(document.body).not.toHaveTextContent("private-backend-error");
    expect(screen.getByLabelText("Apple ID (e-mail)")).toHaveValue("draft@example.org");
  });
  it("does not reflect arbitrary probe errors", async () => {
    renderPanel(); await loaded();
    requestMutation.mockRejectedValue(new Error("secret-probe-error"));
    fireEvent.click(screen.getByRole("button", { name: "Sprawdź IMAP: personal" }));
    await screen.findByText("Nie udało się wykonać testu. Sprawdź połączenie z panelem.");
    expect(document.body).not.toHaveTextContent("secret-probe-error");
  });
});
