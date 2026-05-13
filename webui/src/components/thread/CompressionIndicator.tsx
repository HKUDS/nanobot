import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";

interface CompressionIndicatorProps {
  summaryText: string;
  lastActive: string;
}

export function CompressionIndicator({ summaryText, lastActive }: CompressionIndicatorProps) {
  const [expanded, setExpanded] = useState(false);

  const formattedTime = (() => {
    try {
      const d = new Date(lastActive);
      return d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
    } catch {
      return lastActive;
    }
  })();

  return (
    <div className="mx-auto mb-2 w-full max-w-[49.5rem]">
      <div
        className="group relative rounded-lg border border-border/50 bg-muted/30 p-3
                   transition-colors hover:bg-muted/50"
      >
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-2 text-sm text-muted-foreground
                     hover:text-foreground transition-colors cursor-pointer"
          aria-expanded={expanded}
        >
          <FileText className="h-4 w-4 shrink-0" />
          <span>
            Older messages were auto-compressed at{" "}
            <span className="font-medium">{formattedTime}</span>
          </span>
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 ml-auto" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 ml-auto" />
          )}
        </button>

        {expanded && (
          <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
            {summaryText}
          </div>
        )}
      </div>
    </div>
  );
}
