import {
  PromptNavigationIcon,
} from "@/components/icons/product-icons";
import { useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui/sheet";
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
}

const ROW_HEIGHT = 88;

export function PromptNavigator({
  messages,
  prompts: suppliedPrompts,
  onJumpToPrompt,
}: PromptNavigatorProps) {
  const { i18n, t } = useTranslation();
  const prompts = useMemo(() => suppliedPrompts ?? userPromptAnchors(messages), [suppliedPrompts, messages]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const [listTop, setListTop] = useState(0);

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
        type="button"
        variant="ghost"
        size="icon"
        className={cn(
          "host-no-drag h-8 w-8 rounded-control text-muted-foreground/80",
          "hover:text-foreground",
        )}
        aria-label={t("thread.promptNavigator.open")}
        onClick={() => { setListTop(0); setOpen(true); }}
      >
        <PromptNavigationIcon className="h-4 w-4" />
      </Button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          aria-describedby={undefined}
          className="w-[min(92vw,24rem)] gap-0 p-0 sm:max-w-[24rem]"
        >
          <div className="border-b px-5 pb-4 pt-5">
            <SheetTitle className="text-base font-medium">
              {t("thread.promptNavigator.title")}
            </SheetTitle>
            <div className="relative mt-4">
              <Search
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <SearchInput
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setListTop(0);
                  if (listRef.current) listRef.current.scrollTop = 0;
                }}
                aria-label={t("thread.promptNavigator.search")}
                placeholder={t("thread.promptNavigator.search")}
                className="h-10 rounded-full border-border bg-background pl-9 pr-3 text-sm transition-colors"
              />
            </div>
          </div>

          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 py-2"
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
        </SheetContent>
      </Sheet>
    </>
  );
}

interface PromptNavigatorRowProps {
  row: number;
  locale: string;
  onJump: (promptId: string) => void;
  prompt: PromptAnchor;
}

function PromptNavigatorRow({
  row,
  locale,
  onJump,
  prompt,
}: PromptNavigatorRowProps) {
  const { t } = useTranslation();
  const timestamp = fmtDateTime(prompt.createdAt, locale);
  return (
    <button
      type="button"
      data-prompt-row={row}
      className={cn(
        "h-[88px] w-full overflow-hidden rounded-control px-3 py-3 text-left transition",
        "hover:bg-accent focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
      )}
      aria-label={t("thread.promptNavigator.jumpTo", { label: prompt.label })}
      onClick={() => onJump(prompt.id)}
    >
      <div className="line-clamp-2 whitespace-pre-wrap break-words text-sm leading-5 text-foreground">
        {prompt.preview}
      </div>
      {timestamp ? (
        <div className="mt-1 text-[10px] leading-4 text-muted-foreground/75">
          {timestamp}
        </div>
      ) : null}
    </button>
  );
}
