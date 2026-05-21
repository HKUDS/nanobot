import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { deriveTitle } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

interface SessionSearchDialogProps {
  open: boolean;
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  titleOverrides?: Record<string, string>;
  onOpenChange: (open: boolean) => void;
  onSelect: (key: string) => void;
}

export function SessionSearchDialog({
  open,
  sessions,
  activeKey,
  loading,
  titleOverrides = {},
  onOpenChange,
  onSelect,
}: SessionSearchDialogProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const normalizedQuery = query.trim().toLowerCase();
  const sessionResults = useMemo(() => {
    if (!open) return [];
    if (!normalizedQuery) return sessions;
    const terms = normalizedQuery.split(/\s+/).filter(Boolean);
    return sessions.filter((session) =>
      sessionMatchesTerms(session, terms, titleOverrides[session.key]),
    );
  }, [normalizedQuery, open, sessions, titleOverrides]);
  const itemCount = sessionResults.length;
  const shortcutLabel = useMemo(getSearchShortcutLabel, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setHighlightedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [normalizedQuery]);

  useEffect(() => {
    setHighlightedIndex((index) =>
      itemCount === 0 ? 0 : Math.min(index, itemCount - 1),
    );
  }, [itemCount]);

  const handleSelect = (key: string) => {
    onOpenChange(false);
    onSelect(key);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((index) =>
        itemCount === 0 ? 0 : (index + 1) % itemCount,
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) =>
        itemCount === 0 ? 0 : (index - 1 + itemCount) % itemCount,
      );
      return;
    }
    if (event.key === "Enter") {
      const highlighted = sessionResults[highlightedIndex];
      if (!highlighted) return;
      event.preventDefault();
      handleSelect(highlighted.key);
    }
  };

  const emptyLabel = normalizedQuery
    ? t("sidebar.noSearchResults")
    : t("chat.noSessions");
  const sectionLabel = normalizedQuery
    ? t("sidebar.searchResults")
    : t("sidebar.recent");

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className={cn(
          "max-h-[min(34rem,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-[42rem] gap-0 overflow-hidden p-0",
          "rounded-2xl border border-border/70 bg-popover/95 text-popover-foreground shadow-2xl backdrop-blur-xl",
          "sm:rounded-2xl",
        )}
      >
        <DialogTitle className="sr-only">{t("sidebar.searchAria")}</DialogTitle>
        <DialogDescription className="sr-only">
          {t("sidebar.searchPlaceholder")}
        </DialogDescription>
        <div className="flex h-14 items-center gap-3 border-b border-border/60 px-5">
          <Search
            className="h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("sidebar.searchPlaceholder")}
            aria-label={t("sidebar.searchAria")}
            className="h-full min-w-0 flex-1 bg-transparent text-[15px] font-medium text-foreground outline-none placeholder:text-muted-foreground/75"
          />
          <kbd className="hidden h-6 shrink-0 items-center rounded-md border border-border/70 bg-muted/60 px-2 text-[11px] font-medium text-muted-foreground sm:inline-flex">
            {shortcutLabel}
          </kbd>
        </div>

        <div className="min-h-0 overflow-y-auto overscroll-contain p-2">
          <section>
            <div className="px-2 pb-1.5 pt-1 text-[12px] font-medium text-muted-foreground/70">
              {sectionLabel}
            </div>

            {loading && sessions.length === 0 ? (
              <div className="px-3 py-7 text-[13px] text-muted-foreground">
                {t("chat.loading")}
              </div>
            ) : sessionResults.length === 0 ? (
              <div className="px-3 py-7 text-[13px] text-muted-foreground">
                {emptyLabel}
              </div>
            ) : (
              <ul className="space-y-1">
                {sessionResults.map((session, index) => {
                  const title = titleOverrides[session.key]?.trim() ||
                    session.title?.trim() ||
                    deriveTitle(session.preview, t("chat.newChat"));
                  const preview = session.preview.trim();
                  const showPreview =
                    preview.length > 0 &&
                    preview.toLowerCase() !== title.trim().toLowerCase();
                  const highlighted = index === highlightedIndex;
                  const active = session.key === activeKey;
                  return (
                    <li key={session.key}>
                      <button
                        type="button"
                        onClick={() => handleSelect(session.key)}
                        onMouseEnter={() => setHighlightedIndex(index)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex min-h-12 w-full min-w-0 rounded-xl px-3 py-2.5 text-left transition-colors",
                          highlighted
                            ? "bg-accent text-accent-foreground"
                            : "text-popover-foreground hover:bg-accent/75 hover:text-accent-foreground",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium leading-5">
                            {title}
                          </span>
                          {showPreview ? (
                            <span
                              className={cn(
                                "block truncate text-[12px] leading-4",
                                highlighted
                                  ? "text-accent-foreground/70"
                                  : "text-muted-foreground",
                              )}
                            >
                              {preview}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function sessionMatchesTerms(
  session: ChatSummary,
  terms: string[],
  titleOverride?: string,
) {
  const haystack = [
    titleOverride,
    session.title,
    session.preview,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return terms.every((term) => haystack.includes(term));
}

function getSearchShortcutLabel() {
  if (typeof navigator === "undefined") return "Ctrl K";
  const platform = navigator.platform.toLowerCase();
  const apple =
    platform.includes("mac") ||
    platform.includes("iphone") ||
    platform.includes("ipad");
  return apple ? "⌘K" : "Ctrl K";
}
