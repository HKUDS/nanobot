import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import {
  parseProviderObject,
  type ProviderAdvancedField,
  type ProviderForm,
} from "@/components/settings/models/providerForm";
import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";

const PARAMETER_FIELDS = [
  { field: "extra_headers", formKey: "extraHeaders", titleKey: "settings.providers.extraHeaders", placeholder: '{"X-Header":"value"}' },
  { field: "extra_query", formKey: "extraQuery", titleKey: "settings.providers.extraQuery", placeholder: '{"api-version":"2024-02-01"}' },
  { field: "extra_body", formKey: "extraBody", titleKey: "settings.providers.extraBody", placeholder: '{"service_tier":"priority"}' },
] as const;

function parameterSummary(value: string, t: TFunction): string {
  if (!value.trim()) return t("settings.values.notConfigured");
  const parsed = parseProviderObject(value);
  return parsed
    ? t("settings.providers.parameterCount", { count: Object.keys(parsed).length })
    : t("settings.values.configured");
}

export function ProviderParameterFields({ fields, form, onChange }: {
  fields: ProviderAdvancedField[];
  form: ProviderForm;
  onChange: (value: Partial<ProviderForm>) => void;
}) {
  const { t } = useTranslation();
  const visible = PARAMETER_FIELDS.filter((item) => fields.includes(item.field));
  if (!visible.length) return null;

  return (
    <div className="min-w-0 overflow-hidden rounded-floating border border-border/60 md:col-span-2">
      {visible.map((item) => {
        const title = t(item.titleKey);
        return (
          <SettingsTextEditor key={item.field} title={title}
            value={form[item.formKey]} placeholder={item.placeholder}
            onSave={(value) => onChange({ [item.formKey]: value })}
            trigger={
              <button type="button" className="settings-hover flex min-h-12 w-full items-center gap-3 border-b border-border/60 px-3 py-3 text-left last:border-b-0">
                <span className="min-w-0 flex-1 text-[13px] font-medium">{title}</span>
                <span className="shrink-0 text-[12px] text-muted-foreground">{parameterSummary(form[item.formKey], t)}</span>
                <span className="shrink-0 text-[13px] text-muted-foreground">{t("settings.actions.edit")}</span>
              </button>
            }
          />
        );
      })}
    </div>
  );
}
