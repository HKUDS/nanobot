import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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

function CredentialNotice({ configured }: { configured: boolean }) {
  const { t } = useTranslation();
  return (
    <p className="text-[12px] leading-5 text-muted-foreground">
      {configured
        ? t("settings.integrations.secret.configured", { defaultValue: "Hasło aplikacji jest zapisane. Puste pole zachowuje obecne hasło. Zmiana loginu lub serwera wymaga ponownego podania hasła; zapis nie sprawdza połączenia." })
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

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || refreshing) return;
    const payload: IcloudIntegrationUpdate = {
      username: form.username.trim(), timezone: form.timezone.trim(),
      management_calendar: form.management_calendar.trim(), sleep_hours: form.sleep_hours,
      default_wake_time: form.default_wake_time,
      morning_preparation_minutes: form.morning_preparation_minutes,
      briefing_minutes_after_wake: form.briefing_minutes_after_wake,
      auto_manage_sleep: form.auto_manage_sleep,
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
    <form aria-label={tx("icloud.form", "Konfiguracja iCloud")} onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy} className="min-w-0 space-y-4 p-4 sm:p-5">
        <p className="text-[13px] text-muted-foreground">
          {tx("icloud.description", "Kalendarz iCloud przez CalDAV i hasło aplikacji Apple. Bez logowania OAuth.")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={tx("icloud.username", "Apple ID (e-mail)")}>
            <Input type="email" required autoComplete="username" value={form.username} onChange={(event) => change({ username: event.target.value })} />
          </Field>
          <Field label={tx("icloud.timezone", "Strefa czasowa")}>
            <Input required placeholder="Europe/Warsaw" value={form.timezone} onChange={(event) => change({ timezone: event.target.value })} />
          </Field>
          <Field label={tx("icloud.calendar", "Kalendarz zarządzany")}>
            <Input required value={form.management_calendar} onChange={(event) => change({ management_calendar: event.target.value })} />
          </Field>
          <Field label={tx("icloud.wakeTime", "Domyślna godzina pobudki")}>
            <Input type="time" required value={form.default_wake_time} onChange={(event) => change({ default_wake_time: event.target.value })} />
          </Field>
          <Field label={tx("icloud.sleepHours", "Długość snu (godziny)")}>
            <Input type="number" required min={4} max={12} step="0.25" value={form.sleep_hours} onChange={(event) => change({ sleep_hours: Number(event.target.value) })} />
          </Field>
          <Field label={tx("icloud.preparation", "Poranne przygotowanie (minuty)")}>
            <Input type="number" required min={0} max={360} step={1} value={form.morning_preparation_minutes} onChange={(event) => change({ morning_preparation_minutes: Number(event.target.value) })} />
          </Field>
          <Field label={tx("icloud.briefing", "Odprawa po pobudce (minuty)")}>
            <Input type="number" required min={0} max={180} step={1} value={form.briefing_minutes_after_wake} onChange={(event) => change({ briefing_minutes_after_wake: Number(event.target.value) })} />
          </Field>
          <Field label={tx("icloud.password", "Hasło aplikacji iCloud")}>
            <Input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </Field>
        </div>
        <CredentialNotice configured={config.credential_configured} />
        <div className="flex items-center justify-between gap-3 text-[13px]">
          <span>{tx("icloud.sleep", "Automatyczne zarządzanie snem (konfiguracja)")}</span>
          <ToggleButton checked={form.auto_manage_sleep} label={tx("icloud.sleep", "Automatyczne zarządzanie snem (konfiguracja)")} onChange={(value) => change({ auto_manage_sleep: value })} />
        </div>
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

interface MailRuleDraft {
  name: string;
  destination: string;
  senderGlobs: string;
  subjectContains: string;
}
interface MailDraft {
  id: string;
  email: string;
  host: string;
  port: number;
  username: string;
  allowedFolders: string;
  rules: MailRuleDraft[];
}
const newAccount: MailDraft = {
  id: "", email: "", host: "", port: 993, username: "", allowedFolders: "INBOX", rules: [],
};
function mailDraft(account: MailIntegrationAccount): MailDraft {
  return {
    id: account.id, email: account.email, host: account.host,
    port: account.port, username: account.username,
    allowedFolders: account.allowed_folders.join("\n"),
    rules: account.rules.map((rule) => ({
      name: rule.name, destination: rule.destination,
      senderGlobs: rule.sender_globs.join("\n"), subjectContains: rule.subject_contains.join("\n"),
    })),
  };
}
const lines = (value: string) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

export function MailIntegrationForm({
  accounts, busy, refreshing, onSave,
}: FormStateProps & {
  accounts: MailIntegrationAccount[];
  onSave: (payload: MailIntegrationUpdate) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, defaultValue: string) => t(`settings.integrations.${key}`, { defaultValue });
  const [selectedId, setSelectedId] = useState(accounts[0]?.id ?? "");
  // Only non-secret drafts are retained when switching accounts.
  const [drafts, setDrafts] = useState(() => new Map<string, MailDraft>());
  const [password, setPassword] = useState("");
  const account = accounts.find((item) => item.id === selectedId);
  const form = drafts.get(selectedId) ?? (account ? mailDraft(account) : newAccount);
  const duplicateId = !selectedId && accounts.some((item) => item.id === form.id.trim());
  const change = (value: Partial<MailDraft>) => {
    setDrafts((previous) => new Map(previous).set(selectedId, { ...form, ...value }));
  };
  const changeRule = (index: number, value: Partial<MailRuleDraft>) => {
    change({ rules: form.rules.map((rule, i) => i === index ? { ...rule, ...value } : rule) });
  };
  const select = (id: string) => {
    setSelectedId(id);
    setPassword("");
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || refreshing || duplicateId) return;
    const payload: MailIntegrationUpdate = {
      id: form.id.trim(), email: form.email.trim(), host: form.host.trim(),
      port: form.port, username: form.username.trim(), allowed_folders: lines(form.allowedFolders),
      rules: form.rules.map((rule) => ({
        name: rule.name.trim(), destination: rule.destination.trim(),
        sender_globs: lines(rule.senderGlobs), subject_contains: lines(rule.subjectContains),
      })),
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
        <div className="grid gap-4 sm:grid-cols-2">
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
        </div>
        {duplicateId ? <p role="alert" className="text-[13px] text-destructive">{tx("mail.duplicate", "Ten identyfikator już istnieje. Wybierz konto z listy albo użyj nowego identyfikatora.")}</p> : null}
        <CredentialNotice configured={account?.credential_configured ?? false} />
        <Field label={tx("mail.folders", "Dozwolone foldery (jeden w wierszu)")}>
          <Textarea rows={3} value={form.allowedFolders} onChange={(event) => change({ allowedFolders: event.target.value })} />
        </Field>
        <div className="space-y-3">
          <h3 className="text-[14px] font-medium">{tx("mail.rules", "Podstawowe reguły (tylko konfiguracja)")}</h3>
          {form.rules.length === 0 ? <p className="text-[12px] text-muted-foreground">{tx("mail.noRules", "Brak reguł dla tego konta.")}</p> : null}
          {form.rules.map((rule, index) => (
            <fieldset key={index} className="min-w-0 rounded-control border border-border/55 p-3">
              <legend className="px-1 text-[13px]">{t("settings.integrations.mail.rule", { defaultValue: "Reguła {{number}}", number: index + 1 })}</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={tx("mail.ruleName", "Nazwa reguły")}>
                  <Input required value={rule.name} onChange={(event) => changeRule(index, { name: event.target.value })} />
                </Field>
                <Field label={tx("mail.destination", "Folder docelowy")}>
                  <Input required value={rule.destination} onChange={(event) => changeRule(index, { destination: event.target.value })} />
                </Field>
                <Field label={tx("mail.sender", "Nadawca / glob (jeden w wierszu)")}>
                  <Textarea rows={2} placeholder="*@example.com" value={rule.senderGlobs} onChange={(event) => changeRule(index, { senderGlobs: event.target.value })} />
                </Field>
                <Field label={tx("mail.subject", "Fragment tematu (jeden w wierszu)")}>
                  <Textarea rows={2} value={rule.subjectContains} onChange={(event) => changeRule(index, { subjectContains: event.target.value })} />
                </Field>
              </div>
              <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={() => change({ rules: form.rules.filter((_, i) => i !== index) })}>
                {tx("mail.removeRule", "Usuń regułę ze szkicu")}
              </Button>
            </fieldset>
          ))}
          <Button type="button" variant="outline" onClick={() => change({ rules: [...form.rules, { name: "", destination: "", senderGlobs: "", subjectContains: "" }] })}>
            {tx("mail.addRule", "Dodaj regułę")}
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-[12px] text-muted-foreground">
            {drafts.has(selectedId) || password ? tx("unsaved", "Niezapisane zmiany") : null}
          </span>
          <Button type="submit" disabled={busy || refreshing || duplicateId}>
            {tx("mail.save", "Zapisz konfigurację konta")}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
