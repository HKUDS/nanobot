import { useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import { ProviderPicker } from "@/components/settings/shared/ModelControls";
import { Input } from "@/components/ui/input";

const PRESETS = [900, 1800, 3600, 21600, 43200, 86400];

type ControlProps = Pick<ComponentProps<typeof Input>,
  "id" | "disabled" | "aria-label" | "aria-describedby" | "aria-invalid">;

function formatDuration(seconds: number, locale: string): string {
  const [unit, divisor] = seconds % 3600 === 0 ? ["hour", 3600] as const
    : seconds % 60 === 0 ? ["minute", 60] as const : ["second", 1] as const;
  return new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "long" }).format(seconds / divisor);
}

export function ShellRuntimeControl({
  value, maximum, controlProps, error, onChange, onReject,
}: {
  value: string;
  maximum?: number;
  controlProps: ControlProps;
  error?: { id: string; message: string };
  onChange: (value: string) => void;
  onReject: (message: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [customSelected, setCustomSelected] = useState(false);
  const presets = PRESETS.filter((seconds) => maximum === undefined || seconds <= maximum);
  if (maximum !== undefined && !presets.includes(maximum)) presets.push(maximum);
  const custom = customSelected || controlProps["aria-invalid"] === true
    || (value !== "0" && !presets.includes(Number(value)));
  const limitId = `${controlProps.id}-limit`;
  const describedBy = `${controlProps["aria-describedby"] ?? ""}${maximum === undefined ? "" : ` ${limitId}`}`.trim();
  const unit = new Intl.NumberFormat(i18n.language, {
    style: "unit", unit: "second", unitDisplay: "short",
  }).formatToParts(2).find((part) => part.type === "unit")?.value;
  return (
    <div className="w-full space-y-1.5">
      <ProviderPicker
        triggerProps={{ ...controlProps, id: custom ? `${controlProps.id}-preset` : controlProps.id,
          "aria-describedby": describedBy }}
        value={custom ? "custom" : value}
        emptyLabel={t("settings.runtimeConfig.commandRuntime.custom")}
        providers={[
          ...presets.map((seconds) => ({ name: String(seconds), label: formatDuration(seconds, i18n.language) })),
          { name: "0", label: t("settings.runtimeConfig.commandRuntime.noLimit") },
          { name: "custom", label: t("settings.runtimeConfig.commandRuntime.custom") },
        ]}
        onChange={(next) => {
          setCustomSelected(next === "custom");
          if (next !== "custom") onChange(next);
        }}
      />
      {custom ? <div className="relative">
        <Input {...controlProps} aria-label={t("settings.runtimeConfig.commandRuntime.customLabel")}
          aria-describedby={describedBy} type="number" inputMode="numeric"
          min={1} max={maximum} step={1} autoComplete="off" value={value === "0" ? "" : value}
          className="h-9 rounded-full pr-12 text-[13px] aria-[invalid=true]:border-destructive [&::-webkit-inner-spin-button]:appearance-none"
          onChange={(event) => {
            const next = event.target.value;
            const seconds = Number(next);
            if (next !== "" && (!Number.isSafeInteger(seconds) || seconds < 1
              || (maximum !== undefined && seconds > maximum))) {
              onReject(maximum === undefined ? t("settings.runtimeConfig.numberError")
                : t("settings.runtimeConfig.commandRuntime.rangeError", { max: maximum.toLocaleString(i18n.language) }));
              return;
            }
            setCustomSelected(true);
            onChange(next);
          }} />
        <span aria-hidden className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12px] text-muted-foreground">{unit}</span>
      </div> : null}
      {maximum !== undefined ? <p id={limitId} className="text-[12px] leading-4 text-muted-foreground">
        {t("settings.runtimeConfig.commandRuntime.limit", { duration: formatDuration(maximum, i18n.language) })}
      </p> : null}
      {error ? <p id={error.id} role="alert" className="text-[12px] leading-4 text-destructive">{error.message}</p> : null}
    </div>
  );
}
