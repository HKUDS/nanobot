import { useMemo, useState, type ComponentProps } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function TimezonePicker({ value, onChange, ...triggerProps }: {
  value: string;
  onChange: (value: string) => void;
} & Pick<ComponentProps<typeof Button>, "id" | "aria-label" | "aria-describedby" | "aria-invalid" | "disabled">) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const options = useMemo(() => {
    const now = new Date();
    return [...new Set(["UTC", ...Intl.supportedValuesOf("timeZone"), value].filter(Boolean))]
      .sort().map((zone) => {
        try {
          const name = new Intl.DateTimeFormat(i18n.language, { timeZone: zone, timeZoneName: "longGeneric" })
            .formatToParts(now).find((part) => part.type === "timeZoneName")?.value ?? zone;
          const offset = new Intl.DateTimeFormat("en", { timeZone: zone, timeZoneName: "longOffset" })
            .formatToParts(now).find((part) => part.type === "timeZoneName")?.value ?? "";
          return { zone, detail: `${name} · ${offset.replace("GMT", "UTC")}` };
        } catch {
          // Keep a server-supported timezone visible even if this browser cannot format it.
          return { zone, detail: zone };
        }
      });
  }, [i18n.language, value]);
  const filtered = options.filter(({ zone, detail }) =>
    `${zone.replaceAll("_", " ")} ${zone} ${detail}`.toLocaleLowerCase(i18n.language)
      .includes(query.trim().toLocaleLowerCase(i18n.language)));
  const select = (zone: string) => { onChange(zone); setOpen(false); };
  const navigation = useComboboxNavigation({
    open, values: filtered.map(({ zone }) => zone), selectedValue: value,
    onSelect: select, onClose: () => setOpen(false),
  });
  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); setQuery(""); }}>
      <PopoverTrigger asChild>
        <Button {...triggerProps} type="button" variant="outline"
          className="h-9 w-full justify-between rounded-full border-input bg-background px-3 text-[13px] font-normal shadow-none">
          <span className="truncate">{value}</span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)] p-1.5">
        <Input {...navigation.inputProps} value={query} onChange={(event) => setQuery(event.target.value)}
          aria-label={t("sidebar.searchAria")} placeholder={t("sidebar.searchPlaceholder")}
          className="mb-1.5 h-9 rounded-full" />
        <div {...navigation.listProps} aria-label={triggerProps["aria-label"]} className="max-h-64 overflow-y-auto">
          {filtered.map(({ zone, detail }) => (
            <ComboboxOption key={zone} {...navigation.getOptionProps(zone)} className="block">
              <span className="block">{zone}</span>
              <span className="block text-xs text-muted-foreground">{detail}</span>
            </ComboboxOption>
          ))}
        </div>
        {!filtered.length ? <p role="status" className="p-2 text-xs text-muted-foreground">{t("settings.timezoneNoMatches")}</p> : null}
      </PopoverContent>
    </Popover>
  );
}
