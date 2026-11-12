import type { ComponentProps } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function RemoveActionButton({ children, className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      {...props}
      className={cn("rounded-full text-muted-foreground hover:text-destructive", className)}
    >
      <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
      {children}
    </Button>
  );
}
