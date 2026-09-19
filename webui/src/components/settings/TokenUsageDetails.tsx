import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogLayoutContext, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { SettingsPayload } from "@/lib/types";
import { TokenUsageModelTrend } from "@/components/settings/TokenUsageModelTrend";

type Usage = NonNullable<SettingsPayload["usage"]>;

export function TokenUsageDetails({ days, models, modelDays }: {
  days: { date: string; usage?: Usage["days"][number] }[];
  models?: Usage["providers_30d"];
  modelDays?: Usage["model_days_30d"];
}) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const sum = (key: "total_tokens" | "requests" | "cache_read_tokens" | "cache_read_observed_input_tokens") =>
    days.reduce((total, day) => total + (day.usage?.[key] ?? 0), 0);
  const total = sum("total_tokens");
  const observed = sum("cache_read_observed_input_tokens");
  const metrics = [
    [t("settings.usage.totalTokens"), number.format(total)],
    [t("settings.usage.requests"), number.format(sum("requests"))],
    [t("settings.usage.cacheHitRate"), observed ? percent.format(sum("cache_read_tokens") / observed) : "—"],
  ];
  return (
    <DialogLayoutContext.Provider value={null}>
      <Dialog>
        <DialogTrigger asChild>
          <button type="button" className="settings-hover flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
            {t("settings.usage.viewDetails")}<ChevronRight className="size-3.5" aria-hidden />
          </button>
        </DialogTrigger>
        <DialogContent className="w-[min(1100px,calc(100vw-32px))] max-w-none gap-5 p-5 pt-10 sm:p-7 sm:pt-10" aria-describedby={undefined}>
          <DialogTitle className="sr-only">{t("settings.usage.shortTitle")}</DialogTitle>
          <dl className="grid grid-cols-3 gap-3">
            {metrics.map(([label, value], index) => <div key={label} title={index === 2 ? t("settings.usage.cacheRateHelp") : undefined}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-lg font-medium tabular-nums sm:text-2xl">{value}</dd>
            </div>)}
          </dl>
          {modelDays?.length ? <TokenUsageModelTrend days={days} modelDays={modelDays} models={models} /> : <p className="text-sm text-muted-foreground">{t("settings.usage.modelsUnavailable")}</p>}
        </DialogContent>
      </Dialog>
    </DialogLayoutContext.Provider>
  );
}
