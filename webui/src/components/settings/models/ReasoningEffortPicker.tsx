import { useRef, useState } from "react";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useProviderModelCatalog } from "@/hooks/useProviderModelCatalog";
import type { SettingsPayload } from "@/lib/types";

const NO_PROVIDER = {};
const DEFAULT_VALUE = ":default";

export function ReasoningEffortPicker({ token, provider, model, savedValues, value, onChange }: {
  token: string;
  provider: SettingsPayload["providers"][number] | undefined;
  model: string;
  savedValues?: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const typing = useRef(false);
  const restoreFocus = useRef(false);
  const { payload } = useProviderModelCatalog({
    revision: provider ?? NO_PROVIDER,
    token,
    provider: provider?.name ?? "",
    enabled: open && !!model && !!provider?.configured && provider.model_catalog !== "unsupported",
  });
  const efforts = payload?.models.find((entry) => entry.id === model)?.reasoning_efforts ?? savedValues ?? [];
  const values = [DEFAULT_VALUE, ...new Set(efforts.filter(Boolean))];
  const close = () => { restoreFocus.current = true; setOpen(false); };
  const navigation = useComboboxNavigation({
    open,
    values,
    selectedValue: value || DEFAULT_VALUE,
    onSelect: (selected) => { onChange(selected === DEFAULT_VALUE ? "" : selected); close(); },
    onClose: close,
  });
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div className="w-full">
          <Input
            ref={input}
            {...navigation.inputProps}
            aria-label={t("settings.models.reasoningEffort")}
            value={value}
            placeholder={t("settings.values.default")}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            onClick={() => { typing.current = false; setOpen(true); }}
            onChange={(event) => { typing.current = true; onChange(event.target.value); }}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (!open && ["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) {
                event.preventDefault();
                typing.current = false;
                setOpen(true);
                return;
              }
              if (!open) return;
              if (event.key === "Enter" && typing.current) {
                event.preventDefault();
                close();
                return;
              }
              if (["ArrowDown", "ArrowUp"].includes(event.key)) typing.current = false;
              navigation.inputProps.onKeyDown(event);
            }}
            className="h-9 text-[13px]"
          />
        </div>
      </PopoverAnchor>
      <PopoverContent
        align="end"
        className="w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] p-1.5"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (restoreFocus.current) input.current?.focus({ preventScroll: true });
          restoreFocus.current = false;
        }}
        onEscapeKeyDown={() => { restoreFocus.current = true; }}
        onInteractOutside={(event) => { if (event.target === input.current) event.preventDefault(); }}
      >
        <div {...navigation.listProps}>
          {values.map((effort) => (
            <ComboboxOption key={effort} {...navigation.getOptionProps(effort)}
              className="flex items-center justify-between gap-2 px-3 py-2 text-[13px]">
              <span>{effort === DEFAULT_VALUE ? t("settings.values.default") : effort}</span>
              {effort === (value || DEFAULT_VALUE) ? <Check className="h-4 w-4" aria-hidden /> : null}
            </ComboboxOption>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
