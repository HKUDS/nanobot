import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogDescription, DialogLayoutContext, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TokenUsageModels } from "@/components/settings/TokenUsageModels";
import { TokenUsageModelTrend } from "@/components/settings/TokenUsageModelTrend";

type Usage = NonNullable<SettingsPayload["usage"]>;

export function TokenUsageDetails({ days, models, modelDays }: {
  days: { date: string; usage?: Usage["days"][number] }[];
  models?: Usage["providers_30d"];
  modelDays?: Usage["model_days_30d"];
}) {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState("trend");
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
      <Dialog onOpenChange={open => { if (open) setView(modelDays?.length ? "trend" : "models"); }}>
        <DialogTrigger asChild>
          <button type="button" className="settings-hover flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
            {t("settings.usage.viewDetails")}<ChevronRight className="size-3.5" aria-hidden />
          </button>
        </DialogTrigger>
        <DialogContent className="w-[min(1100px,calc(100vw-32px))] max-w-none gap-5 p-5 pt-10 sm:p-7 sm:pt-10" aria-describedby={undefined}>
          <DialogTitle className="sr-only">{t("settings.usage.shortTitle")}</DialogTitle>
          <DialogDescription className="text-xs tabular-nums">{days[0].date} – {days[days.length - 1].date}</DialogDescription>
          <dl className="grid grid-cols-3 gap-3">
            {metrics.map(([label, value], index) => <div key={label} title={index === 2 ? t("settings.usage.cacheRateHelp") : undefined}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-lg font-medium tabular-nums sm:text-2xl">{value}</dd>
            </div>)}
          </dl>
          <div className="flex gap-1 min-[900px]:hidden">
            {[["trend", t("settings.usage.modelTrend")], ["models", t("settings.usage.byModel")]].map(([key, label]) => <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)} className={cn("rounded-full px-3 py-1.5 text-xs", view === key ? "bg-muted text-foreground" : "settings-hover text-muted-foreground")}>{label}</button>)}
          </div>
          <div className="grid min-w-0 gap-7 min-[900px]:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <div className={cn("min-w-0 min-[900px]:block", view !== "trend" && "hidden")}>
              {modelDays?.length ? <TokenUsageModelTrend days={days} modelDays={modelDays} /> : <p className="text-sm text-muted-foreground">{t("settings.usage.modelsUnavailable")}</p>}
            </div>
            <div className={cn("min-w-0 min-[900px]:block", view !== "models" && "hidden")}>
              <TokenUsageModels models={models} total={total} />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </DialogLayoutContext.Provider>
  );
}
