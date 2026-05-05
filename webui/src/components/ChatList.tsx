import { MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

interface ChatListProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  loading?: boolean;
}

function titleFor(s: ChatSummary, fallbackTitle: string): string {
  const p = s.preview?.trim();
  if (p) return p.length > 48 ? `${p.slice(0, 45)}…` : p;
  return fallbackTitle;
}

export function ChatList({
  sessions,
  activeKey,
  onSelect,
  onRequestDelete,
  loading,
}: ChatListProps) {
  const { t } = useTranslation();
  if (loading && sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] text-muted-foreground">
        {t("chat.loading")}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-xs text-muted-foreground">
        {t("chat.noSessions")}
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <ul className="space-y-0.5 px-2 py-1">
        {sessions.map((s) => {
          const active = s.key === activeKey;
          const title = titleFor(
            s,
            t("chat.fallbackTitle", { id: s.chatId.slice(0, 6) }),
          );
          return (
            <li key={s.key}>
              <div
                className={cn(
                  "group flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors",
                  active
                    ? "bg-sidebar-accent/80 text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.4)]"
                    : "text-sidebar-foreground/88 hover:bg-sidebar-accent/45",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(s.key)}
                  className="flex min-w-0 flex-1 flex-col items-start text-left"
                >
                  <span className="w-full truncate font-medium leading-5">{title}</span>
                  <span className="text-[10.5px] text-muted-foreground/80">
                    {relativeTime(s.updatedAt ?? s.createdAt) || "—"}
                  </span>
                </button>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger
                    className={cn(
                      "inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity",
                      "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100",
                      "focus-visible:opacity-100",
                      active && "opacity-100",
                    )}
                    aria-label={t("chat.actions", { title })}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    onCloseAutoFocus={(event) => event.preventDefault()}
                  >
                    <DropdownMenuItem
                      onSelect={() => {
                        window.setTimeout(() => onRequestDelete(s.key, title), 0);
                      }}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      {t("chat.delete")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </li>
          );
        })}
      </ul>
    </ScrollArea>
  );
}
