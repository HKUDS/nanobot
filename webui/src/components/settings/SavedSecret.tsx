import { Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { secretToggleClassName } from "@/components/ui/secret-input";

/** The server's masked hint is display text, never an editable credential value. */
export function SavedSecret({ hint, editLabel, onEdit, disabled }: {
  hint: string;
  editLabel: string;
  onEdit: () => void;
  disabled?: boolean;
}) {
  return <div className="relative w-full">
    <div className="flex h-9 items-center rounded-full border border-input bg-background px-3 pr-11 text-[13px] text-muted-foreground">
      {hint}
    </div>
    <Button type="button" variant="ghost" size="icon" disabled={disabled}
      onClick={onEdit} aria-label={editLabel} className={secretToggleClassName}>
      <Pencil className="h-3.5 w-3.5" aria-hidden />
    </Button>
  </div>;
}
