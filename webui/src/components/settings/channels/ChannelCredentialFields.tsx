import { useTranslation } from "react-i18next";

import type {
  ChannelConfigField,
  ChannelFieldSection,
  ChannelSetupRequirement,
} from "@/components/settings/channels/catalog";
import {
  CredentialForm,
  channelFieldInputId,
  type CredentialFormProps,
} from "@/components/settings/channels/CredentialForm";

const CHANNEL_FIELD_SECTION_ORDER: ChannelFieldSection[] = [
  "account",
  "credentials",
  "connection",
  "access",
  "behavior",
  "security",
];

type ChannelFieldGroupsProps = Omit<CredentialFormProps, "fields" | "compact"> & {
  fields: ChannelConfigField[];
  requirements: ChannelSetupRequirement[];
  sectionLabels?: Record<string, string>;
};

export function ChannelFieldGroups({
  fields,
  requirements,
  sectionLabels,
  ...formProps
}: ChannelFieldGroupsProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const labels = new Map(fields.map((field) => [field.key, field.label]));
  const compositeRequirements = requirements.filter(
    (requirement) => requirement.alternatives.length > 1,
  );
  const groups = new Map<string, ChannelConfigField[]>();
  for (const field of fields) {
    const section = field.section ?? "credentials";
    const current = groups.get(section) ?? [];
    current.push(field);
    groups.set(section, current);
  }
  const orderedSections = [
    ...CHANNEL_FIELD_SECTION_ORDER,
    ...[...groups.keys()].filter(
      (section) => !CHANNEL_FIELD_SECTION_ORDER.includes(section as ChannelFieldSection),
    ),
  ];

  return (
    <div className="space-y-5">
      {compositeRequirements.map((requirement, index) => (
        <div
          key={index}
          className="rounded-control border border-border/60 bg-background/55 px-3 py-2.5"
        >
          <div className="text-[11px] font-semibold text-foreground">
            {tx("settings.channels.chooseCredentialMethod", "Choose one credential method")}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            {requirement.alternatives.map((alternative, alternativeIndex) => (
              <span key={alternative.join("|")} className="contents">
                {alternativeIndex ? <span aria-hidden>{tx("settings.channels.or", "or")}</span> : null}
                <span className="rounded-full bg-muted px-2 py-0.5 text-foreground/85">
                  {alternative.map((key) => labels.get(key) ?? key.split(".").at(-1)).join(" + ")}
                </span>
              </span>
            ))}
          </div>
        </div>
      ))}
      {orderedSections.map((section) => {
        const sectionFields = groups.get(section);
        if (!sectionFields?.length) return null;
        return (
          <fieldset key={section} className="min-w-0">
            <legend className={groups.size === 1 ? "sr-only" : "mb-2 text-[12px] font-medium text-muted-foreground"}>
              {channelFieldSectionLabel(section, tx, sectionLabels)}
            </legend>
            <div>
              <CredentialForm fields={sectionFields} {...formProps} compact />
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}

function channelFieldSectionLabel(
  section: string,
  tx: (key: string, fallback: string) => string,
  sectionLabels?: Record<string, string>,
): string {
  const customLabel = sectionLabels?.[section];
  if (customLabel) return customLabel;

  const fallbacks: Record<ChannelFieldSection, string> = {
    account: "Account",
    credentials: "Credentials",
    connection: "Connection",
    access: "Access",
    behavior: "Behavior",
    security: "Security",
    advanced: "Advanced",
  };
  const fallback = fallbacks[section as ChannelFieldSection];
  if (fallback) return tx(`settings.channels.sections.${section}`, fallback);
  return section
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function channelRequirementErrors(
  fields: ChannelConfigField[],
  requirements: ChannelSetupRequirement[],
  values: Record<string, string>,
  configuredFields: Set<string>,
  clearedSecrets: Set<string>,
  message: string,
): Record<string, string> {
  const fieldByKey = new Map(fields.map((field) => [field.key, field]));
  const present = (key: string) => {
    const field = fieldByKey.get(key);
    if (!field || clearedSecrets.has(key)) return false;
    const value = (values[key] ?? "").trim();
    if (field.kind === "bool") return value === "true";
    if (value) return true;
    return Boolean(field.secret && configuredFields.has(key));
  };
  const errors: Record<string, string> = {};
  for (const requirement of requirements) {
    if (requirement.alternatives.some((alternative) => alternative.every(present))) continue;
    const closest = [...requirement.alternatives].sort(
      (left, right) => left.filter((key) => !present(key)).length - right.filter((key) => !present(key)).length,
    )[0] ?? [];
    for (const key of closest) {
      if (!present(key) && fieldByKey.has(key)) errors[key] = message;
    }
  }
  return errors;
}

export function channelServerValidationErrors(
  fields: ChannelConfigField[],
  missingFields: string[],
  message: string,
): Record<string, string> {
  const missing = new Set(missingFields);
  return Object.fromEntries(
    fields
      .filter((field) => missing.has(field.key) || missing.has(field.key.split(".").at(-1) ?? ""))
      .map((field) => [field.key, message]),
  );
}

export function focusFirstChannelFieldError(errors: Record<string, string>) {
  const key = Object.keys(errors)[0];
  if (!key) return;
  window.requestAnimationFrame(() => {
    document.getElementById(channelFieldInputId(key))?.focus();
  });
}
