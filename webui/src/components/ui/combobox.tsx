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

export function useComboboxNavigation({
  open,
  values,
  selectedValue,
  onSelect,
  onClose,
}: ComboboxNavigationOptions) {
  const listboxId = React.useId();
  const [activeValue, setActiveValue] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      setActiveValue(null);
      return;
    }
    setActiveValue((current) => {
      if (current && values.includes(current)) return current;
      if (selectedValue && values.includes(selectedValue)) return selectedValue;
      return values[0] ?? null;
    });
  }, [open, selectedValue, values]);

  const activeIndex = activeValue ? values.indexOf(activeValue) : -1;
  const activeOptionId = activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined;

  React.useEffect(() => {
    if (!activeOptionId) return;
    const option = document.getElementById(activeOptionId);
    option?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  const move = (offset: number) => {
    if (!values.length) return;
    const nextIndex = activeIndex < 0
      ? offset > 0 ? 0 : values.length - 1
      : (activeIndex + offset + values.length) % values.length;
    setActiveValue(values[nextIndex]);
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
      "data-highlighted": value === activeValue ? "" : undefined,
      tabIndex: -1,
      onPointerMove: () => setActiveValue(value),
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
      "w-full cursor-default text-left data-[highlighted]:bg-muted/85 data-[highlighted]:text-foreground",
      className,
    )}
    {...props}
  />
));
ComboboxOption.displayName = "ComboboxOption";

export { ComboboxOption };
