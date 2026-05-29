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
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
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

  useEffect(() => {
    itemRefs.current = itemRefs.current.slice(0, itemCount);
  }, [itemCount]);

  useEffect(() => {
    if (!open) return;
    itemRefs.current[highlightedIndex]?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [highlightedIndex, open]);

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
          "flex max-h-[min(40rem,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-[42rem] flex-col gap-0 overflow-hidden p-0",
          "rounded-[22px] border border-border bg-background text-foreground shadow-[0_22px_70px_rgba(0,0,0,0.22)]",
          "dark:border-white/14 dark:bg-[#2b2b2b] dark:shadow-[0_26px_90px_rgba(0,0,0,0.44)] sm:rounded-[22px]",
        )}
      >
        <DialogTitle className="sr-only">{t("sidebar.searchAria")}</DialogTitle>
        <DialogDescription className="sr-only">
          {t("sidebar.searchPlaceholder")}
        </DialogDescription>
        <div className="flex h-[62px] shrink-0 items-center gap-3 border-b border-border px-[18px]">
          <Search
            className="h-[18px] w-[18px] shrink-0 text-muted-foreground"
            aria-hidden
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("sidebar.searchPlaceholder")}
            aria-label={t("sidebar.searchAria")}
            className="h-full min-w-0 flex-1 bg-transparent text-[19px] font-normal leading-none text-foreground outline-none placeholder:text-muted-foreground"
          />
        </div>

        <div
          data-testid="session-search-scroll"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2.5 scrollbar-thin scrollbar-track-transparent"
        >
          <section>
            <div className="px-2.5 pb-1.5 pt-1 text-[12px] font-medium text-muted-foreground">
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
              <ul className="space-y-0.5">
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
                        ref={(node) => {
                          itemRefs.current[index] = node;
                        }}
                        type="button"
                        onClick={() => handleSelect(session.key)}
                        onMouseEnter={() => setHighlightedIndex(index)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "grid min-h-[54px] w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-[11px] px-3 py-2 text-left transition-colors",
                          highlighted
                            ? "bg-muted text-foreground"
                            : "text-foreground hover:bg-muted",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium leading-5">
                            {title}
                          </span>
                          {showPreview ? (
                            <span
                              className="block truncate text-[12px] leading-4 text-muted-foreground"
                            >
                              {preview}
                            </span>
                          ) : null}
                        </span>
                        {active ? (
                          <span className="shrink-0 rounded-full bg-muted-foreground/10 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                            {t("common.current", { defaultValue: "Current" })}
                          </span>
                        ) : null}
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
