import { MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

interface ChatListProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  loading?: boolean;
  emptyLabel?: string;
}

function titleFor(s: ChatSummary, fallbackTitle: string): string {
  const p = (s.title || s.preview)?.trim();
  if (p) return p.length > 48 ? `${p.slice(0, 45)}…` : p;
  return fallbackTitle;
}

export function ChatList({
  sessions,
  activeKey,
  onSelect,
  onRequestDelete,
  loading,
  emptyLabel,
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
      <div className="px-3 py-6 text-[12px] leading-5 text-muted-foreground/80">
        {emptyLabel ?? t("chat.noSessions")}
      </div>
    );
  }

  const groups = groupSessions(sessions, {
    today: t("chat.groups.today"),
    yesterday: t("chat.groups.yesterday"),
    earlier: t("chat.groups.earlier"),
  });

  return (
    <ScrollArea className="h-full">
      <div className="space-y-3 px-2 py-1.5">
        {groups.map((group) => (
          <section key={group.label} aria-label={group.label}>
            <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground/65">
              {group.label}
            </div>
            <ul className="space-y-0.5">
              {group.sessions.map((s) => {
                const active = s.key === activeKey;
                const title = titleFor(
                  s,
                  t("chat.fallbackTitle", { id: s.chatId.slice(0, 6) }),
                );
                return (
                  <li key={s.key}>
                    <div
                      className={cn(
                        "group flex min-h-8 items-center gap-2 rounded-xl px-2 text-[13px] transition-colors",
                        active
                          ? "bg-sidebar-accent/70 text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_hsl(var(--sidebar-border)/0.28)]"
                          : "text-sidebar-foreground/82 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onSelect(s.key)}
                        className="min-w-0 flex-1 py-1.5 text-left"
                      >
                        <span className="block w-full truncate font-medium leading-5">{title}</span>
                      </button>
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger
                          className={cn(
                            "inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/75 opacity-0 transition-opacity",
                            "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100",
                            "focus-visible:opacity-100",
                            active && "opacity-100",
                          )}
                          aria-label={t("chat.actions", { title })}
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" />
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
          </section>
        ))}
      </div>
    </ScrollArea>
  );
}

function groupSessions(
  sessions: ChatSummary[],
  labels: { today: string; yesterday: string; earlier: string },
): Array<{ label: string; sessions: ChatSummary[] }> {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const buckets = new Map<string, ChatSummary[]>();

  for (const session of sessions) {
    const timestamp = Date.parse(session.updatedAt ?? session.createdAt ?? "");
    const label = Number.isFinite(timestamp) && timestamp >= startOfToday
      ? labels.today
      : Number.isFinite(timestamp) && timestamp >= startOfYesterday
        ? labels.yesterday
        : labels.earlier;
    const bucket = buckets.get(label) ?? [];
    bucket.push(session);
    buckets.set(label, bucket);
  }

  return [labels.today, labels.yesterday, labels.earlier]
    .map((label) => ({ label, sessions: buckets.get(label) ?? [] }))
    .filter((group) => group.sessions.length > 0);
}
