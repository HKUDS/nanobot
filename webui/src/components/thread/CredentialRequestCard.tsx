import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import type { CredentialRequestUIData } from "@/lib/types";

type CardPhase =
  | { kind: "open" }
  | { kind: "submitting" }
  | { kind: "closed"; status: string };

const TERMINAL_COPY: Record<string, string> = {
  submitted: "credentials.statusSubmitted",
  cancelled: "credentials.statusCancelled",
  expired: "credentials.statusExpired",
};

/** Inline credential form rendered for ``agent_ui`` ``credential_request``
 * messages. Values submit over a dedicated ``credential_submit`` envelope so
 * they never appear in the chat transcript or reach the model. */
export function CredentialRequestCard({ data }: { data: CredentialRequestUIData }) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const status = typeof data.status === "string" ? data.status : undefined;
  const expiresAtMs = typeof data.expires_at === "number" ? data.expires_at * 1000 : null;

  const phase: CardPhase = status
    ? { kind: "closed", status }
    : expiresAtMs !== null && now >= expiresAtMs
      ? { kind: "closed", status: "expired" }
      : submitting
        ? { kind: "submitting" }
        : { kind: "open" };

  useEffect(() => {
    if (status || expiresAtMs === null || now >= expiresAtMs) return;
    const timer = window.setTimeout(() => setNow(Date.now()), expiresAtMs - now + 100);
    return () => window.clearTimeout(timer);
  }, [status, expiresAtMs, now]);

  const fields = useMemo(() => data.fields ?? [], [data.fields]);
  const missingRequired = fields.some(
    (field) => field.required !== false && !(values[field.key] ?? "").trim(),
  );

  const chatId = typeof data.chat_id === "string" ? data.chat_id : "";
  const submit = () => {
    if (phase.kind !== "open" || missingRequired || !chatId) return;
    setSubmitting(true);
    client.submitCredential(chatId, data.request_id, values);
  };
  const cancel = () => {
    if (phase.kind !== "open" || !chatId) return;
    client.cancelCredential(chatId, data.request_id);
    setSubmitting(true);
  };

  return (
    <div
      data-credential-request={data.request_id}
      className={cn(
        "mt-3 w-full max-w-md rounded-floating border border-border/70",
        "bg-muted/30 px-4 py-3",
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium">
        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span>
          {t("credentials.title", {
            service: data.service,
            defaultValue: "Credentials for {{service}}",
          })}
        </span>
      </div>
      {data.reason ? (
        <p className="mt-1 text-[13px]/[1.5] text-muted-foreground">{data.reason}</p>
      ) : null}

      {phase.kind === "open" || phase.kind === "submitting" ? (
        <form
          className="mt-3 flex flex-col gap-2.5"
          autoComplete="off"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {fields.map((field) => (
            <label key={field.key} className="flex flex-col gap-1">
              <span className="text-[12px] font-medium text-muted-foreground">
                {field.label}
                {field.required === false ? (
                  <span className="ms-1 opacity-70">
                    {t("credentials.optional", { defaultValue: "(optional)" })}
                  </span>
                ) : null}
              </span>
              <Input
                type={field.sensitive === false ? "text" : "password"}
                name={`credential-${field.key}`}
                autoComplete="off"
                required={field.required !== false}
                disabled={phase.kind !== "open"}
                value={values[field.key] ?? ""}
                onChange={(event) => setValues((prev) => ({
                  ...prev,
                  [field.key]: event.target.value,
                }))}
              />
            </label>
          ))}
          <p className="text-[11px]/[1.5] text-muted-foreground">
            {t("credentials.notice", {
              defaultValue:
                "Values go directly to the local nanobot runtime and are stored as named secrets. They are not sent as a chat message.",
            })}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <Button
              type="submit"
              size="sm"
              disabled={phase.kind !== "open" || missingRequired}
            >
              {submitting
                ? t("credentials.submitting", { defaultValue: "Submitting…" })
                : t("credentials.submit", { defaultValue: "Submit" })}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={phase.kind !== "open"}
              onClick={cancel}
            >
              {t("credentials.cancel", { defaultValue: "Cancel" })}
            </Button>
          </div>
        </form>
      ) : (
        <div className="mt-2 flex items-center gap-2 text-[13px] text-muted-foreground">
          <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
          <span>
            {t(
              TERMINAL_COPY[phase.status] ?? "credentials.statusClosed",
              phase.status === "submitted"
                ? { defaultValue: "Credentials submitted securely." }
                : phase.status === "cancelled"
                  ? { defaultValue: "Request cancelled." }
                  : { defaultValue: "This credential request is no longer active." },
            )}
          </span>
        </div>
      )}
    </div>
  );
}
