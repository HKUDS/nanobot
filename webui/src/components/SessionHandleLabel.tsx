import type { ReactNode } from "react";

import { InlineTokenHighlight } from "@/components/InlineTokenHighlight";
import { sessionHandleColor } from "@/lib/session-handle";

export function SessionHandleLabel({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  return (
    <InlineTokenHighlight
      color={sessionHandleColor(id)}
    >
      {children}
    </InlineTokenHighlight>
  );
}
