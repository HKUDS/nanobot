import type { ComponentType, ReactNode } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface ComponentExample {
  title: string;
  files: string[];
  description: string;
  options: string;
  code: string;
  Preview: ComponentType;
}

export function Sample({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0 space-y-2">
    <p className="text-xs text-muted-foreground">{label}</p>
    {children}
  </div>;
}

export function StatePicker<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (value: T) => void;
}) {
  return <div className="mb-5 flex flex-wrap items-center gap-3 text-sm">
    <span>{label}</span>
    <Select value={value} onValueChange={(next) => {
      const option = options.find((item) => item === next);
      if (option) onChange(option);
    }}>
      <SelectTrigger aria-label={label} className="min-w-36"><SelectValue /></SelectTrigger>
      <SelectContent>{options.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent>
    </Select>
  </div>;
}
