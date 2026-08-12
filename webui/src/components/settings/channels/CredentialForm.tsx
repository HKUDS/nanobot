import type { ReactNode } from "react";
import { Check, CircleAlert, Eye, EyeOff, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import type { ChannelConfigField } from "@/components/settings/channels/catalog";
import { cn } from "@/lib/utils";

export function channelFieldValue(field: ChannelConfigField, values: Record<string, string>): string {
  return values[field.key] ?? field.defaultValue ?? field.options?.[0]?.value ?? "";
}

export function defaultChannelFieldValues(
  fields: ChannelConfigField[],
  configValues: Record<string, string> | undefined = undefined,
): Record<string, string> {
  return Object.fromEntries(
    fields.map((field) => [
      field.key,
      configValues?.[field.key] ?? field.defaultValue ?? field.options?.[0]?.value ?? "",
    ]),
  );
}

export function channelValuesForSave(
  fields: ChannelConfigField[],
  values: Record<string, string>,
): Record<string, string> {
  const payload: Record<string, string> = {};
  for (const field of fields) {
    const value = channelFieldValue(field, values);
    if (field.secret && !value.trim()) continue;
    payload[field.key] = value;
  }
  return payload;
}

export function channelValuesForSubmit(
  fields: ChannelConfigField[],
  values: Record<string, string>,
  touchedFields: Set<string>,
  clearedSecrets: Set<string> = new Set(),
): Record<string, string | null> {
  const payload: Record<string, string | null> = {};
  for (const field of fields) {
    if (field.secret && clearedSecrets.has(field.key)) {
      payload[field.key] = null;
      continue;
    }
    const touched = touchedFields.has(field.key);
    const value = channelFieldValue(field, values);
    if (field.secret && !value.trim()) continue;
    if (!touched && !value.trim()) continue;
    if (!touched && field.options?.length) continue;
    payload[field.key] = value;
  }
  return payload;
}

export function channelValidationStatusLabel(
  status: string,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const labels: Record<string, string> = {
    connected: "Connected",
    configured: "Configured manually",
    needs_setup: "Needs setup",
    invalid: "Invalid",
    unsupported: "Manual setup",
  };
  return t(`settings.channels.validation.${status}`, {
    defaultValue: labels[status] ?? "Checked",
  });
}

export function channelValidationStatusClass(status: string): string {
  if (status === "connected") {
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-200";
  }
  if (status === "configured") {
    return "bg-blue-500/10 text-blue-700 dark:text-blue-200";
  }
  if (status === "invalid") {
    return "bg-destructive/10 text-destructive";
  }
  return "bg-muted text-muted-foreground";
}

export function channelValidationStatusIcon(status: string): ReactNode {
  if (status === "connected" || status === "configured") {
    return <Check className="h-3.5 w-3.5" aria-hidden />;
  }
  if (status === "invalid") {
    return <X className="h-3.5 w-3.5" aria-hidden />;
  }
  return <CircleAlert className="h-3.5 w-3.5" aria-hidden />;
}

export function channelValidationCheckIcon(status: string): ReactNode {
  if (status === "pass") return <Check className="h-3.5 w-3.5" aria-hidden />;
  if (status === "fail") return <X className="h-3.5 w-3.5" aria-hidden />;
  if (status === "warn") return <CircleAlert className="h-3.5 w-3.5" aria-hidden />;
  return <CircleAlert className="h-3.5 w-3.5" aria-hidden />;
}

export function channelValidationCheckIconClass(status: string): string {
  if (status === "pass") return "text-emerald-600";
  if (status === "fail") return "text-destructive";
  if (status === "warn") return "text-amber-600";
  return "text-muted-foreground";
}

export function CredentialForm({
  fields,
  values,
  configuredFields,
  visibleSecrets,
  onChange,
  onToggleSecret,
  errors = {},
  clearedSecrets = new Set(),
  onClearSecret,
  compact = false,
}: {
  fields: ChannelConfigField[];
  values: Record<string, string>;
  configuredFields?: Set<string>;
  visibleSecrets: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onToggleSecret: (key: string) => void;
  errors?: Record<string, string>;
  clearedSecrets?: Set<string>;
  onClearSecret?: (key: string, clear: boolean) => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className={cn(compact ? "space-y-2.5" : "mt-3 space-y-2.5")}>
      {fields.map((field) => {
        const inputId = `channel-field-${field.key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        const helpId = field.help ? `${inputId}-help` : undefined;
        const error = errors[field.key];
        const errorId = error ? `${inputId}-error` : undefined;
        const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;
        const visible = Boolean(visibleSecrets[field.key]);
        const value = values[field.key] ?? "";
        const clearSecret = clearedSecrets.has(field.key);
        const savedSecret = Boolean(
          field.secret && configuredFields?.has(field.key) && !value.trim() && !clearSecret,
        );
        const showSecretToggle = Boolean(field.secret && value.trim());
        const inputType = field.secret && !visible ? "password" : field.inputType ?? "text";
        const selectedOption = channelFieldValue(field, values);
        const header = (
          <span className="flex items-center justify-between gap-2 text-[11px] font-medium text-foreground/85">
            <span>{field.label}</span>
            {savedSecret ? (
              <span className="font-normal text-muted-foreground">
                {tx("settings.channels.savedSecret", "Saved")}
              </span>
            ) : clearSecret ? (
              <span className="font-normal text-destructive">
                {tx("settings.channels.secretWillBeRemoved", "Will be removed")}
              </span>
            ) : field.optional && !compact ? (
              <span className="font-normal text-muted-foreground">
                {tx("settings.channels.optional", "Optional")}
              </span>
            ) : null}
          </span>
        );
        const help = field.help ? (
          <span id={helpId} className="mt-1 block text-[11px] leading-4 text-muted-foreground">
            {field.help}
          </span>
        ) : null;
        const errorMessage = error ? (
          <span id={errorId} className="mt-1 block text-[11px] leading-4 text-destructive">
            {error}
          </span>
        ) : null;
        if (field.options?.length) {
          return (
            <fieldset key={field.key} className="block">
              <legend className="w-full">{header}</legend>
              <span
                className="mt-1 grid rounded-[10px] bg-muted p-0.5 text-[12px] font-medium text-muted-foreground"
                style={{ gridTemplateColumns: `repeat(${field.options.length}, minmax(0, 1fr))` }}
              >
                {field.options.map((option) => (
                  <label key={option.value} className="relative block">
                    <input
                      type="radio"
                      name={inputId}
                      value={option.value}
                      checked={selectedOption === option.value}
                      onChange={() => onChange(field.key, option.value)}
                      className="peer sr-only"
                    />
                    <span className="grid min-h-11 cursor-pointer place-items-center rounded-[8px] px-2 py-1.5 transition-colors hover:text-foreground peer-checked:bg-background peer-checked:text-foreground peer-checked:ring-1 peer-checked:ring-inset peer-checked:ring-border/45 peer-focus-visible:ring-2 peer-focus-visible:ring-ring sm:min-h-9">
                      {option.label}
                    </span>
                  </label>
                ))}
              </span>
              {help}
              {errorMessage}
            </fieldset>
          );
        }
        return (
          <div key={field.key} className="block">
            <label htmlFor={inputId} className="block">{header}</label>
            <span className="relative mt-1 block">
              <Input
                id={inputId}
                aria-label={field.label}
                aria-invalid={Boolean(error)}
                aria-describedby={describedBy}
                type={inputType}
                autoComplete={field.secret ? "off" : undefined}
                inputMode={field.inputType === "number" ? "numeric" : undefined}
                placeholder={
                  savedSecret
                    ? tx("settings.channels.savedSecretPlaceholder", "Saved secret")
                    : field.placeholder
                }
                value={values[field.key] ?? ""}
                onChange={(event) => onChange(field.key, event.target.value)}
                className={cn(
                  "h-10 rounded-[10px] border-border/60 bg-muted/35 text-base sm:h-9 sm:text-[13px]",
                  error && "border-destructive focus-visible:ring-destructive/30",
                  showSecretToggle && "pr-9",
                )}
              />
              {showSecretToggle ? (
                <button
                  type="button"
                  aria-label={
                    visible
                      ? tx("settings.channels.hideSecret", "Hide secret")
                      : tx("settings.channels.showSecret", "Show secret")
                  }
                  onClick={() => onToggleSecret(field.key)}
                  className="absolute right-0 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground sm:right-1 sm:h-8 sm:w-8"
                >
                  {visible ? (
                    <EyeOff className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Eye className="h-3.5 w-3.5" aria-hidden />
                  )}
                </button>
              ) : null}
              </span>
            {help}
            {errorMessage}
            {field.secret && configuredFields?.has(field.key) && !value.trim() && onClearSecret ? (
              <button
                type="button"
                className="mt-1 min-h-8 text-[11px] font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                onClick={() => onClearSecret(field.key, !clearSecret)}
              >
                {clearSecret
                  ? tx("settings.channels.keepSavedSecret", "Keep saved credential")
                  : tx("settings.channels.removeSavedSecret", "Remove saved credential")}
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
