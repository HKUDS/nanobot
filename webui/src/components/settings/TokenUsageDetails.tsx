import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogLayoutContext, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { SettingsPayload } from "@/lib/types";
import { usageFormats } from "@/lib/usage-number";
import { TokenUsageModelTrend } from "@/components/settings/TokenUsageModelTrend";

type Usage = NonNullable<SettingsPayload["usage"]>;
type DayTotal = NonNullable<Usage["days"][number]>;

export function TokenUsageDetails({ days, models, modelDays, onOpenChange, loading }: {
  days: { date: string; usage?: DayTotal }[];
  models?: Usage["providers_30d"];
  modelDays?: Usage["model_days_30d"];
  onOpenChange?: (open: boolean) => void;
  loading?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const percent = usageFormats(i18n.language).percent;
  const sum = (key: "total_tokens" | "estimated_tokens") =>
    days.reduce((total, day) => total + (day.usage?.[key] ?? 0), 0);
  const total = sum("total_tokens");
  const estimated = sum("estimated_tokens");

  return (
    <DialogLayoutContext.Provider value={null}>
      <Dialog onOpenChange={onOpenChange}>
        <DialogTrigger asChild>
          <button type="button" className="settings-hover flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            {t("settings.usage.viewDetails")}<ChevronRight className="size-3.5" aria-hidden />
          </button>
        </DialogTrigger>
        <DialogContent className="w-[min(1100px,calc(100vw-32px))] max-w-none gap-5 p-5 pt-10 sm:p-7 sm:pt-10" aria-describedby={undefined}>
          <div className="flex items-baseline justify-between gap-4 pr-8">
            <DialogTitle className="text-sm font-medium">{t("settings.usage.shortTitle")}</DialogTitle>
            <span className="text-[11px] text-muted-foreground">{t("settings.usage.last30Days", { defaultValue: "Last 30 days" })}</span>
          </div>
          {estimated > 0 && total > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {t("settings.usage.estimatedShare", {
                defaultValue: "{{percent}} of tokens are estimated",
                percent: percent(estimated / total),
              })}
            </p>
          )}
          {modelDays?.length ? <TokenUsageModelTrend days={days} modelDays={modelDays} models={models} /> : <p className="text-sm text-muted-foreground">{t(loading ? "common.loading" : "settings.usage.modelsUnavailable")}</p>}
        </DialogContent>
      </Dialog>
    </DialogLayoutContext.Provider>
  );
}
