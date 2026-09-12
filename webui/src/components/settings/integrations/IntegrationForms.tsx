import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formControlFocusClassName } from "@/components/ui/form-control";
import type {
  IcloudIntegration,
  IcloudIntegrationUpdate,
  MailIntegrationAccount,
  MailIntegrationUpdate,
} from "@/lib/integrations";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-[13px]">
      <span className="font-medium">{label}</span>
      {children}
    </label>
  );
}

function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

function CredentialNotice({ configured, apple = false }: { configured: boolean; apple?: boolean }) {
  const { t } = useTranslation();
  return (
    <p className="text-[12px] leading-5 text-muted-foreground">
      {configured
        ? apple
          ? t("settings.integrations.secret.appleConfigured", { defaultValue: "Hasło aplikacji jest zapisane i wspólne dla kalendarza oraz poczty iCloud. Puste pole zachowuje je także po zmianie adresu Apple. Zapis nie sprawdza połączenia." })
          : t("settings.integrations.secret.configured", { defaultValue: "Hasło aplikacji jest zapisane. Puste pole zachowuje obecne hasło. Zmiana loginu lub serwera IMAP wymaga nowego hasła; zapis nie sprawdza połączenia." })
        : t("settings.integrations.secret.missing", { defaultValue: "Brak zapisanego hasła aplikacji. Wpisz je, aby skonfigurować dostęp. Zapis nie sprawdza połączenia." })}
    </p>
  );
}

interface FormStateProps {
  busy: boolean;
  refreshing: boolean;
}

export function IcloudIntegrationForm({
  config, busy, refreshing, onSave,
}: FormStateProps & {
  config: IcloudIntegration;
  onSave: (payload: IcloudIntegrationUpdate) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, defaultValue: string) => t(`settings.integrations.${key}`, { defaultValue });
  // A draft takes precedence over fresh server data until it is saved successfully.
  const [draft, setDraft] = useState<IcloudIntegration | null>(null);
  const [password, setPassword] = useState("");
  const form = draft ?? config;
  const change = (value: Partial<IcloudIntegration>) => setDraft({ ...form, ...value });
  useUnsavedWarning(Boolean(draft || password));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || refreshing) return;
    const payload: IcloudIntegrationUpdate = {
      username: form.username.trim(),
      ...(password.trim() ? { password } : {}),
    };
    // Clear immediately, including requests that fail or time out. Never repopulate from GET.
    setPassword("");
    try {
      if (await onSave(payload)) setDraft(null);
    } finally {
      setPassword("");
    }
  };

  return (
    <form id="apple-integration-settings" aria-label={tx("icloud.form", "Konfiguracja iCloud")} onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy} className="min-w-0 space-y-4 p-4 sm:p-5">
        <p className="text-[13px] text-muted-foreground">
          {tx("icloud.accountDescription", "Jedno konto Apple dla kalendarza CalDAV i poczty iCloud. Użyj hasła aplikacji Apple, nie głównego hasła konta. Sen i pobudkę skonfigurujemy osobno.")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={tx("icloud.username", "Apple ID (e-mail)")}>
            <Input type="email" required autoComplete="username" value={form.username} onChange={(event) => change({ username: event.target.value })} />
          </Field>
          <Field label={tx("icloud.password", "Hasło aplikacji iCloud")}>
            <Input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </Field>
        </div>
        <CredentialNotice configured={config.credential_configured} apple />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-[12px] text-muted-foreground">
            {draft || password ? tx("unsaved", "Niezapisane zmiany") : null}
          </span>
          <Button type="submit" disabled={busy || refreshing}>
            {tx("icloud.save", "Zapisz konfigurację iCloud")}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}

interface MailDraft {
  id: string;
  email: string;
  host: string;
  port: number;
  username: string;
}
const newAccount: MailDraft = {
  id: "", email: "", host: "", port: 993, username: "",
};
function mailDraft(account: MailIntegrationAccount): MailDraft {
  return {
    id: account.id, email: account.email, host: account.host,
    port: account.port, username: account.username,
  };
}

export function MailIntegrationForm({
  accounts, busy, refreshing, onSave,
}: FormStateProps & {
  accounts: MailIntegrationAccount[];
  onSave: (payload: MailIntegrationUpdate) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, defaultValue: string) => t(`settings.integrations.${key}`, { defaultValue });
  const [selection, setSelectedId] = useState<string | null>(null);
  const selectedId = selection ?? accounts[0]?.id ?? "";
  // Only non-secret drafts are retained when switching accounts.
  const [drafts, setDrafts] = useState(() => new Map<string, MailDraft>());
  const [password, setPassword] = useState("");
  const account = accounts.find((item) => item.id === selectedId);
  const linkedApple = account?.managed_by === "icloud";
  const form = drafts.get(selectedId) ?? (account ? mailDraft(account) : newAccount);
  const duplicateId = !selectedId && accounts.some((item) => item.id === form.id.trim());
  const change = (value: Partial<MailDraft>) => {
    setDrafts((previous) => new Map(previous).set(selectedId, { ...form, ...value }));
  };
  useUnsavedWarning(drafts.size > 0 || Boolean(password));
  const select = (id: string) => {
    setSelectedId(id);
    setPassword("");
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || refreshing || duplicateId || linkedApple) return;
    const payload: MailIntegrationUpdate = {
      id: form.id.trim(), email: form.email.trim(), host: form.host.trim(),
      port: form.port, username: form.username.trim(),
      ...(password.trim() ? { password } : {}),
    };
    setPassword("");
    try {
      if (await onSave(payload)) {
        setDrafts((previous) => {
          const next = new Map(previous);
          next.delete(selectedId);
          return next;
        });
        setSelectedId(payload.id);
      }
    } finally {
      setPassword("");
    }
  };

  return (
    <form aria-label={tx("mail.form", "Konfiguracja poczty IMAP")} onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy} className="min-w-0 space-y-4 p-4 sm:p-5">
        <p className="text-[13px] leading-5 text-muted-foreground">
          {tx("mail.description", "Hasło aplikacji przez IMAPS/TLS (zwykle port 993). OAuth nie jest obsługiwany. Tryb próbny (dry-run): bez wysyłania, przenoszenia i usuwania wiadomości.")}
        </p>
        {accounts.length === 0 ? <p className="text-[13px]">{tx("mail.empty", "Brak kont pocztowych. Dodaj pierwsze konto poniżej.")}</p> : null}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1">
            <Field label={tx("mail.select", "Konto pocztowe")}>
              <select className={`h-10 w-full min-w-0 rounded-control border border-input bg-background px-3 ${formControlFocusClassName}`} value={selectedId} onChange={(event) => select(event.target.value)}>
                {accounts.map((item) => <option key={item.id} value={item.id}>{item.email || item.id} ({item.id})</option>)}
                <option value="">{tx("mail.new", "Nowe konto")}</option>
              </select>
            </Field>
          </div>
          <Button type="button" variant="outline" onClick={() => select("")}>
            {tx("mail.add", "Dodaj nowe konto")}
          </Button>
        </div>
        <p className="text-[12px] text-muted-foreground">
          {tx("mail.switchHint", "Zapis dotyczy tylko wybranego konta, nie usuwa pozostałych. Zmiana konta zachowuje szkic, ale czyści wpisane hasło.")}
        </p>
        {linkedApple ? (
          <div className="space-y-2 rounded-control border border-border/55 p-3 text-[13px]">
            <p>{tx("mail.linkedApple", "Konto połączone z Apple — adres i hasło są wspólne z kalendarzem. Zmieniaj je w sekcji Apple, bez tworzenia drugiego konta.")}</p>
            <Button type="button" variant="outline" onClick={() => {
              const form = document.getElementById("apple-integration-settings");
              form?.scrollIntoView({ behavior: "smooth", block: "start" });
              form?.querySelector("input")?.focus({ preventScroll: true });
            }}>{tx("mail.editApple", "Edytuj konto Apple")}</Button>
          </div>
        ) : null}
        <fieldset disabled={linkedApple} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <Field label={tx("mail.id", "Identyfikator konta")}>
            <Input required readOnly={Boolean(selectedId)} value={form.id} onChange={(event) => change({ id: event.target.value })} />
          </Field>
          <Field label={tx("mail.email", "Adres e-mail")}>
            <Input type="email" required value={form.email} onChange={(event) => change({ email: event.target.value })} />
          </Field>
          <Field label={tx("mail.host", "Serwer IMAP")}>
            <Input required placeholder="imap.example.com" value={form.host} onChange={(event) => change({ host: event.target.value })} />
          </Field>
          <Field label={tx("mail.port", "Port IMAPS/TLS")}>
            <Input type="number" required min={1} max={65535} step={1} value={form.port} onChange={(event) => change({ port: Number(event.target.value) })} />
          </Field>
          <Field label={tx("mail.username", "Login IMAP")}>
            <Input required autoComplete="username" value={form.username} onChange={(event) => change({ username: event.target.value })} />
          </Field>
          <Field label={tx("mail.password", "Hasło aplikacji IMAP")}>
            <Input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </Field>
        </fieldset>
        {duplicateId ? <p role="alert" className="text-[13px] text-destructive">{tx("mail.duplicate", "Ten identyfikator już istnieje. Wybierz konto z listy albo użyj nowego identyfikatora.")}</p> : null}
        <CredentialNotice configured={account?.credential_configured ?? false} apple={linkedApple} />
        <p className="text-[12px] leading-5 text-muted-foreground">
          {account?.folder_policy === "allowlist"
            ? tx("mail.legacyFolders", "To starsze konto zachowuje dotychczasowe ograniczenia folderów. Nowe konta mają dostęp do wszystkich folderów. Reguły ustalimy osobno — zapis formularza ich nie zmienia.")
            : tx("mail.allFolders", "Wszystkie foldery są dostępne od początku i wykrywane automatycznie. Reguły ustalimy osobno — ten formularz ich nie tworzy ani nie usuwa.")}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-[12px] text-muted-foreground">
            {drafts.has(selectedId) || password ? tx("unsaved", "Niezapisane zmiany") : null}
          </span>
          <Button type="submit" disabled={busy || refreshing || duplicateId || linkedApple}>
            {tx("mail.save", "Zapisz konfigurację konta")}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
