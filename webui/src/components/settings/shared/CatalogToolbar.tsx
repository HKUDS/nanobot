import { useId, type ComponentPropsWithRef, type ReactNode } from "react";
import { Search } from "lucide-react";

import { SearchInput } from "@/components/ui/input";
import { ToggleButton } from "@/components/ui/toggle-button";
import { SETTINGS_SEARCH_INPUT_CLASS } from "@/components/settings/shared/SettingsControls";
import { cn } from "@/lib/utils";

type CatalogSearchProps = Omit<ComponentPropsWithRef<typeof SearchInput>, "className">;

export function CatalogSearch(props: CatalogSearchProps) {
  return (
    <div className="catalog-search">
      <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <SearchInput aria-label={props.placeholder} {...props}
        className={cn("h-9 rounded-control ps-9 text-ui-label", SETTINGS_SEARCH_INPUT_CLASS)} />
    </div>
  );
}

export function CatalogToolbar({ search, children }: { search?: CatalogSearchProps; children: ReactNode }) {
  return (
    <div className="catalog-toolbar">
      {children}
      {search && <CatalogSearch {...search} />}
    </div>
  );
}

export function CatalogControls({ children }: { children: ReactNode }) {
  return <div className="catalog-controls text-ui-label">{children}</div>;
}

export function CatalogToggle({ label, checked, onChange }: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="catalog-toggle cursor-pointer text-muted-foreground hover:text-foreground">
      <span>{label}</span>
      <ToggleButton label={label} checked={checked} onChange={onChange} />
    </label>
  );
}

export function CatalogFilter<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: ReactNode }>;
  onChange: (value: T) => void;
}) {
  const name = useId();
  return (
    <div className="catalog-choices" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <label key={option.value} className="relative cursor-pointer">
          <input className="peer sr-only" type="radio" name={name} value={option.value}
            checked={value === option.value} onChange={() => onChange(option.value)} />
          <span className="flex min-h-8 items-center gap-1 rounded-compact px-2 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground peer-checked:bg-muted peer-checked:text-foreground peer-focus-visible:ring-2 peer-focus-visible:ring-inset peer-focus-visible:ring-ring">
            {option.label}
          </span>
        </label>
      ))}
    </div>
  );
}
