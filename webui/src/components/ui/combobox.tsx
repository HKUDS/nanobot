import * as React from "react";

import {
  floatingItemClassName,
  floatingItemFocusClassName,
} from "@/components/ui/floating-surface";
import { cn } from "@/lib/utils";

interface ComboboxNavigationOptions {
  open: boolean;
  values: readonly string[];
  selectedValue?: string;
  onSelect: (value: string) => void;
  onClose: () => void;
}

interface ActiveOption {
  value: string | null;
  source: "initial" | "keyboard" | "pointer";
}

export function useComboboxNavigation({
  open,
  values,
  selectedValue,
  onSelect,
  onClose,
}: ComboboxNavigationOptions) {
  const listboxId = React.useId();
  const [activeOption, setActiveOption] = React.useState<ActiveOption>({ value: null, source: "initial" });
  const activeValue = activeOption.value;

  React.useEffect(() => {
    setActiveOption((current) => {
      if (open && current.value && values.includes(current.value)) return current;
      const value = open
        ? selectedValue && values.includes(selectedValue) ? selectedValue : values[0] ?? null
        : null;
      return current.value === value && current.source === "initial"
        ? current : { value, source: "initial" };
    });
  }, [open, selectedValue, values]);

  const activeIndex = activeValue ? values.indexOf(activeValue) : -1;
  const activeOptionId = activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined;

  React.useEffect(() => {
    if (!activeOptionId || activeOption.source !== "keyboard") return;
    const option = document.getElementById(activeOptionId);
    option?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId, activeOption.source]);

  const move = (offset: number) => {
    if (!values.length) return;
    const nextIndex = activeIndex < 0
      ? offset > 0 ? 0 : values.length - 1
      : (activeIndex + offset + values.length) % values.length;
    setActiveOption({ value: values[nextIndex], source: "keyboard" });
  };

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return;
    switch (event.key) {
      case "ArrowDown":
        if (values.length) {
          event.preventDefault();
          move(1);
        }
        break;
      case "ArrowUp":
        if (values.length) {
          event.preventDefault();
          move(-1);
        }
        break;
      case "Enter":
        if (activeValue) {
          event.preventDefault();
          onSelect(activeValue);
        }
        break;
      case "Escape":
        event.preventDefault();
        onClose();
        break;
    }
  };

  const expanded = open && values.length > 0;
  const inputProps = {
    role: "combobox" as const,
    "aria-autocomplete": "list" as const,
    "aria-controls": expanded ? listboxId : undefined,
    "aria-expanded": expanded,
    "aria-activedescendant": expanded ? activeOptionId : undefined,
    onKeyDown: onInputKeyDown,
  };

  const listProps = {
    id: listboxId,
    role: "listbox" as const,
  };

  const getOptionProps = (value: string) => {
    const index = values.indexOf(value);
    return {
      id: `${listboxId}-option-${index}`,
      role: "option" as const,
      "aria-selected": value === activeValue,
      "data-highlighted": value === activeValue && activeOption.source === "keyboard" ? "" : undefined,
      tabIndex: -1,
      onPointerMove: (event: React.PointerEvent<HTMLButtonElement>) => {
        if (event.pointerType === "touch") return;
        setActiveOption((current) => current.value === value && current.source === "pointer"
          ? current : { value, source: "pointer" });
      },
      onPointerLeave: () => {
        setActiveOption((current) => current.source === "pointer" && current.value === value
          ? { value: null, source: "pointer" } : current);
      },
      onClick: () => onSelect(value),
    };
  };

  return { inputProps, listProps, getOptionProps };
}

const ComboboxOption = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      floatingItemClassName,
      floatingItemFocusClassName,
      "w-full cursor-default text-left settings-hover data-[highlighted]:bg-[var(--control-hover-fill)] data-[highlighted]:text-foreground",
      className,
    )}
    {...props}
  />
));
ComboboxOption.displayName = "ComboboxOption";

export { ComboboxOption };
