import {
  PromptNavigationIcon,
} from "@/components/icons/product-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  type PromptAnchor,
  userPromptAnchors,
} from "@/components/thread/promptNavigation";
import { fmtDateTime } from "@/lib/format-time";
import type { UIMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface PromptNavigatorProps {
  messages: UIMessage[];
  prompts?: PromptAnchor[];
  onJumpToPrompt: (promptId: string) => void;
  shortcutEnabled?: boolean;
}

const ROW_HEIGHT = 64;

export function PromptNavigator({
  messages,
  prompts: suppliedPrompts,
  onJumpToPrompt,
  shortcutEnabled = true,
}: PromptNavigatorProps) {
  const { i18n, t } = useTranslation();
  const prompts = useMemo(() => suppliedPrompts ?? userPromptAnchors(messages), [suppliedPrompts, messages]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const [listTop, setListTop] = useState(0);
  const [highlighted, setHighlighted] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      if (!shortcutEnabled || !prompts.length || event.defaultPrevented || event.repeat || event.isComposing
        || event.altKey || event.shiftKey || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "f") return;
      if (!open && (triggerRef.current?.closest("[hidden], [aria-hidden=true]") || document.querySelector("[role=dialog][data-state=open]"))) return;
      event.preventDefault();
      setListTop(0); setOpen(true);
      inputRef.current?.focus(); inputRef.current?.select();
    };
    window.addEventListener("keydown", keyDown);
    return () => window.removeEventListener("keydown", keyDown);
  }, [shortcutEnabled, prompts.length, open]);
  useEffect(() => { if (open) { setQuery(""); setHighlighted(0); setListTop(0); } }, [open]);

  const filteredPrompts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return prompts;
    return prompts.filter((prompt) =>
      `${prompt.label}\n${prompt.preview}`.toLocaleLowerCase().includes(needle),
    );
  }, [prompts, query]);
  const firstRow = Math.max(0, Math.floor(listTop / ROW_HEIGHT) - 2);
  const lastRow = firstRow + Math.ceil(window.innerHeight / ROW_HEIGHT) + 5;

  if (prompts.length === 0) return null;

  const jump = (promptId: string) => {
    setOpen(false);
    onJumpToPrompt(promptId);
  };

  return (
    <>
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon"
        className={cn(
          "host-no-drag h-8 w-8 rounded-control text-muted-foreground/80",
          "hover:text-foreground",
        )}
        aria-label={t("thread.promptNavigator.open")}
        aria-keyshortcuts="Control+F Meta+F"
        onClick={() => { setListTop(0); setOpen(true); }}
      >
        <PromptNavigationIcon className="h-4 w-4" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          showCloseButton={false}
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            inputRef.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const target = openerRef.current?.isConnected ? openerRef.current : triggerRef.current;
            target?.focus({ preventScroll: true });
          }}
          className="session-search-dialog flex max-h-[min(40rem,100%)] w-[calc(100vw-2rem)] max-w-[42rem] flex-col gap-0 overflow-hidden p-0"
        >
            <DialogTitle className="sr-only">
              {t("thread.promptNavigator.title")}
            </DialogTitle>
            <div className="session-search-input flex h-[62px] shrink-0 items-center gap-3 border-b border-border px-[18px]">
              <Search
                aria-hidden
                className="h-[18px] w-[18px] shrink-0 text-muted-foreground"
              />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setListTop(0);
                  setHighlighted(0);
                  if (listRef.current) listRef.current.scrollTop = 0;
                }}
                aria-label={t("thread.promptNavigator.search")}
                placeholder={t("thread.promptNavigator.search")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && filteredPrompts[highlighted]) { event.preventDefault(); jump(filteredPrompts[highlighted].id); }
                  if ((event.key === "ArrowDown" || event.key === "ArrowUp") && filteredPrompts.length) {
                    event.preventDefault();
                    const next = (highlighted + (event.key === "ArrowDown" ? 1 : -1) + filteredPrompts.length) % filteredPrompts.length;
                    setHighlighted(next);
                    if (listRef.current) { listRef.current.scrollTop = next * ROW_HEIGHT; setListTop(next * ROW_HEIGHT); }
                  }
                }}
                className="h-full min-w-0 flex-1 bg-transparent text-[19px] font-normal leading-none text-foreground outline-none placeholder:text-muted-foreground"
              />
            </div>

          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2.5 scrollbar-thin scrollbar-track-transparent"
            onScroll={(event) => setListTop(event.currentTarget.scrollTop)}
            onKeyDown={(event) => {
              const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-prompt-row]");
              if (!button || !listRef.current) return;
              const index = Number(button.dataset.promptRow);
              let next = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: filteredPrompts.length - 1 }[event.key];
              if (event.key === "Tab") {
                if (!event.shiftKey && index === lastRow - 1) next = index + 1;
                if (event.shiftKey && index === firstRow && firstRow > 0) next = index - 1;
              }
              if (next === undefined || next < 0 || next >= filteredPrompts.length) return;
              event.preventDefault();
              listRef.current.scrollTop = next * ROW_HEIGHT;
              setListTop(listRef.current.scrollTop);
              requestAnimationFrame(() => listRef.current?.querySelector<HTMLButtonElement>(`[data-prompt-row="${next}"]`)?.focus());
            }}>
            {filteredPrompts.length > 0 ? (
              <div style={{ paddingTop: firstRow * ROW_HEIGHT, paddingBottom: Math.max(0, filteredPrompts.length - lastRow) * ROW_HEIGHT }}>
                {filteredPrompts.slice(firstRow, lastRow).map((prompt, offset) => (
                  <PromptNavigatorRow
                    key={prompt.id}
                    row={firstRow + offset}
                    highlighted={highlighted === firstRow + offset}
                    onHighlight={() => setHighlighted(firstRow + offset)}
                    locale={i18n.resolvedLanguage || i18n.language}
                    prompt={prompt}
                    onJump={jump}
                  />
                ))}
              </div>
            ) : (
              <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                {t("thread.promptNavigator.noResults")}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface PromptNavigatorRowProps {
  row: number;
  locale: string;
  onJump: (promptId: string) => void;
  prompt: PromptAnchor;
  highlighted: boolean;
  onHighlight: () => void;
}

function PromptNavigatorRow({
  row,
  locale,
  onJump,
  prompt,
  highlighted,
  onHighlight,
}: PromptNavigatorRowProps) {
  const { t } = useTranslation();
  const timestamp = fmtDateTime(prompt.createdAt, locale);
  return (
    <button
      type="button"
      data-prompt-row={row}
      className={cn(
        "h-16 w-full overflow-hidden rounded-control px-3 py-2 text-left transition-colors",
        "hover:bg-muted focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        highlighted && "bg-muted",
      )}
      aria-label={t("thread.promptNavigator.jumpTo", { label: prompt.label })}
      onClick={() => onJump(prompt.id)}
      onMouseEnter={onHighlight}
    >
      <div className="truncate text-[14px] font-medium leading-5 text-foreground">
        {prompt.preview}
      </div>
      {timestamp ? (
        <div className="mt-1 text-[12px] leading-4 text-muted-foreground">
          {timestamp}
        </div>
      ) : null}
    </button>
  );
}
