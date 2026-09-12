import type { WebUIMutationTransport } from "@/lib/api";
import { fetchWithTimeout } from "@/lib/http";

export interface IcloudIntegration {
  username: string;
  timezone: string;
  management_calendar: string;
  sleep_hours: number;
  default_wake_time: string;
  morning_preparation_minutes: number;
  briefing_minutes_after_wake: number;
  auto_manage_sleep: boolean;
  credential_configured: boolean;
}

export interface MailIntegrationRule {
  name: string;
  destination: string;
  sender_globs: string[];
  subject_contains: string[];
}

export interface MailIntegrationAccount {
  id: string;
  email: string;
  host: string;
  port: number;
  username: string;
  allowed_folders: string[];
  rules: MailIntegrationRule[];
  credential_configured: boolean;
}

export interface IntegrationsPayload {
  icloud: IcloudIntegration;
  mail: {
    accounts: MailIntegrationAccount[];
    dry_run: true;
    reconcile_interval_seconds: number;
  };
  memory: {
    enabled: boolean;
    rerank_mode: string;
    items: number | null;
    status: string | null;
  };
  evolution: {
    enabled: boolean;
    mode: string;
    capture_content: boolean;
    experiences: number | null;
    status: string | null;
  };
  services: Array<{ id: string; label: string; state: string | null; detail: string }>;
  notes: string[];
  exported: boolean;
  message?: string;
}

export type IcloudIntegrationUpdate = Omit<IcloudIntegration, "credential_configured"> & {
  password?: string;
};
export type MailIntegrationUpdate = Omit<MailIntegrationAccount, "credential_configured"> & {
  password?: string;
};

// Validate and pick public fields at the wire boundary; never reflect an error body
// or accidental extra credentials from a response into the settings UI.
function invalidResponse(): never {
  throw new Error("Invalid integrations response");
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalidResponse();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  return typeof value === "string" ? value : invalidResponse();
}
function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : invalidResponse();
}
function boolean(value: unknown): boolean {
  return typeof value === "boolean" ? value : invalidResponse();
}
function array<T>(value: unknown, parse: (item: unknown) => T): T[] {
  return Array.isArray(value) ? value.map(parse) : invalidResponse();
}
function count(value: unknown): number | null {
  return value == null ? null : number(value);
}
function status(value: unknown): string | null {
  return value == null || value === "" ? null : text(value);
}

export function parseIntegrationsPayload(value: unknown): IntegrationsPayload {
  const payload = record(value);
  const icloud = record(payload.icloud);
  const mail = record(payload.mail);
  const memory = record(payload.memory);
  const evolution = record(payload.evolution);
  if (mail.dry_run !== true) return invalidResponse();
  return {
    icloud: {
      username: text(icloud.username),
      timezone: text(icloud.timezone),
      management_calendar: text(icloud.management_calendar),
      sleep_hours: number(icloud.sleep_hours),
      default_wake_time: text(icloud.default_wake_time),
      morning_preparation_minutes: number(icloud.morning_preparation_minutes),
      briefing_minutes_after_wake: number(icloud.briefing_minutes_after_wake),
      auto_manage_sleep: boolean(icloud.auto_manage_sleep),
      credential_configured: boolean(icloud.credential_configured),
    },
    mail: {
      accounts: array(mail.accounts, (value) => {
        const account = record(value);
        return {
          id: text(account.id), email: text(account.email), host: text(account.host),
          port: number(account.port), username: text(account.username),
          allowed_folders: array(account.allowed_folders, text),
          credential_configured: boolean(account.credential_configured),
          rules: array(account.rules, (value) => {
            const rule = record(value);
            return {
              name: text(rule.name), destination: text(rule.destination),
              sender_globs: array(rule.sender_globs, text),
              subject_contains: array(rule.subject_contains, text),
            };
          }),
        };
      }),
      dry_run: true,
      reconcile_interval_seconds: number(mail.reconcile_interval_seconds),
    },
    memory: {
      enabled: boolean(memory.enabled), rerank_mode: text(memory.rerank_mode),
      items: count(memory.items), status: status(memory.status),
    },
    evolution: {
      enabled: boolean(evolution.enabled), mode: text(evolution.mode),
      capture_content: boolean(evolution.capture_content),
      experiences: count(evolution.experiences), status: status(evolution.status),
    },
    services: array(payload.services, (value) => {
      const service = record(value);
      return {
        id: text(service.id), label: text(service.label),
        state: status(service.state), detail: text(service.detail),
      };
    }),
    notes: array(payload.notes, text),
    exported: boolean(payload.exported),
    ...(payload.message == null ? {} : { message: text(payload.message) }),
  };
}

export async function fetchIntegrations(token: string, signal?: AbortSignal) {
  const response = await fetchWithTimeout("/api/settings/integrations", {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
    cache: "no-store",
    signal,
  }, 20_000);
  // Error bodies may contain submitted credentials. Do not read/display them.
  if (!response.ok) throw new Error("Unable to load integrations");
  return parseIntegrationsPayload(await response.json());
}

function withOptionalPassword<T extends { password?: string }>(payload: T) {
  const { password, ...fields } = payload;
  return password?.trim() ? { ...fields, password } : fields;
}

export async function saveIcloudIntegration(
  client: WebUIMutationTransport,
  payload: IcloudIntegrationUpdate,
) {
  return parseIntegrationsPayload(await client.requestMutation<unknown>(
    "settings.integrations.icloud", withOptionalPassword(payload), 20_000,
  ));
}

export async function saveMailIntegration(
  client: WebUIMutationTransport,
  payload: MailIntegrationUpdate,
) {
  return parseIntegrationsPayload(await client.requestMutation<unknown>(
    "settings.integrations.mail", withOptionalPassword(payload), 20_000,
  ));
}

export async function prepareIntegrations(client: WebUIMutationTransport) {
  return parseIntegrationsPayload(await client.requestMutation<unknown>(
    "settings.integrations.prepare", {}, 20_000,
  ));
}
