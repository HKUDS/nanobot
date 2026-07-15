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
): Record<string, string> {
  const payload: Record<string, string> = {};
  for (const field of fields) {
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
  compact = false,
}: {
  fields: ChannelConfigField[];
  values: Record<string, string>;
  configuredFields?: Set<string>;
  visibleSecrets: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onToggleSecret: (key: string) => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className={cn(compact ? "space-y-2.5" : "mt-3 space-y-2.5")}>
      {fields.map((field) => {
        const visible = Boolean(visibleSecrets[field.key]);
        const value = values[field.key] ?? "";
        const savedSecret = Boolean(field.secret && configuredFields?.has(field.key) && !value.trim());
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
            ) : field.optional && !compact ? (
              <span className="font-normal text-muted-foreground">
                {tx("settings.channels.optional", "Optional")}
              </span>
            ) : null}
          </span>
        );
        const help = field.help ? (
          <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">
            {field.help}
          </span>
        ) : null;
        if (field.options?.length) {
          return (
            <div key={field.key} className="block">
              {header}
              <span
                role="radiogroup"
                aria-label={field.label}
                className="mt-1 grid rounded-[10px] bg-muted/75 p-0.5 text-[12px] font-medium text-muted-foreground shadow-[inset_0_0_0_1px_rgba(15,23,42,0.035)]"
                style={{ gridTemplateColumns: `repeat(${field.options.length}, minmax(0, 1fr))` }}
              >
                {field.options.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={selectedOption === option.value}
                    onClick={() => onChange(field.key, option.value)}
                    className={cn(
                      "min-h-8 rounded-[8px] px-2 py-1.5 transition-colors hover:text-foreground",
                      selectedOption === option.value
                        && "bg-background text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.10),inset_0_0_0_1px_rgba(15,23,42,0.055)]",
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </span>
              {help}
            </div>
          );
        }
        return (
          <label key={field.key} className="block">
            {header}
            <span className="relative mt-1 block">
              <Input
                aria-label={field.label}
                type={inputType}
                inputMode={field.inputType === "number" ? "numeric" : undefined}
                placeholder={
                  savedSecret
                    ? tx("settings.channels.savedSecretPlaceholder", "Saved secret")
                    : field.placeholder
                }
                value={values[field.key] ?? ""}
                onChange={(event) => onChange(field.key, event.target.value)}
                className={cn(
                  "h-9 rounded-[10px] border-border/60 bg-muted/35 text-[13px]",
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
                  className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
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
          </label>
        );
      })}
    </div>
  );
}
