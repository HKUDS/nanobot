import { useMemo, useState } from "react";
import { ListTree, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  type PromptAnchor,
  userPromptAnchors,
} from "@/components/thread/promptNavigation";
import { fmtDateTime } from "@/lib/format";
import type { UIMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface PromptNavigatorProps {
  bottomOffset: number;
  messages: UIMessage[];
  onJumpToPrompt: (promptId: string) => void;
}

export function PromptNavigator({
  bottomOffset,
  messages,
  onJumpToPrompt,
}: PromptNavigatorProps) {
  const { i18n, t } = useTranslation();
  const prompts = useMemo(() => userPromptAnchors(messages), [messages]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const filteredPrompts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return prompts;
    return prompts.filter((prompt) =>
      `${prompt.label}\n${prompt.preview}`.toLocaleLowerCase().includes(needle),
    );
  }, [prompts, query]);

  if (prompts.length === 0) return null;

  const jump = (promptId: string) => {
    setOpen(false);
    onJumpToPrompt(promptId);
  };

  return (
    <>
      <div
        className="pointer-events-none absolute right-4 z-20"
        style={{ bottom: Math.max(104, bottomOffset + 12) }}
      >
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={cn(
            "pointer-events-auto h-8 w-8 rounded-full border-border/70 bg-background/90 shadow-md backdrop-blur",
            "text-muted-foreground hover:text-foreground",
          )}
          aria-label={t("thread.promptNavigator.open")}
          onClick={() => setOpen(true)}
        >
          <ListTree className="h-4 w-4" />
        </Button>
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          className="w-[min(92vw,24rem)] gap-0 p-0 sm:max-w-[24rem]"
        >
          <div className="border-b px-5 pb-4 pt-5">
            <SheetTitle className="text-base font-medium">
              {t("thread.promptNavigator.title")}
            </SheetTitle>
            <SheetDescription className="mt-1 text-xs">
              {t("thread.promptNavigator.description", { count: prompts.length })}
            </SheetDescription>
            <div className="relative mt-4">
              <Search
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label={t("thread.promptNavigator.search")}
                placeholder={t("thread.promptNavigator.search")}
                className={cn(
                  "h-10 w-full rounded-full border border-border bg-background pl-9 pr-3 text-sm",
                  "outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20",
                )}
              />
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
            {filteredPrompts.length > 0 ? (
              <div className="space-y-1">
                {filteredPrompts.map((prompt) => (
                  <PromptNavigatorRow
                    key={prompt.id}
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
  locale: string;
  onJump: (promptId: string) => void;
  prompt: PromptAnchor;
}

function PromptNavigatorRow({
  locale,
  onJump,
  prompt,
}: PromptNavigatorRowProps) {
  const { t } = useTranslation();
  const timestamp = fmtDateTime(prompt.createdAt, locale);
  return (
    <button
      type="button"
      className={cn(
        "w-full rounded-xl px-3 py-3 text-left transition",
        "hover:bg-accent focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
      )}
      aria-label={t("thread.promptNavigator.jumpTo", { label: prompt.label })}
      onClick={() => onJump(prompt.id)}
    >
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <span>{t("thread.promptNavigator.promptNumber", { number: prompt.index + 1 })}</span>
        {timestamp ? (
          <>
            <span aria-hidden>·</span>
            <span>{timestamp}</span>
          </>
        ) : null}
      </div>
      <div className="mt-1 max-h-20 overflow-hidden whitespace-pre-wrap break-words text-sm leading-5 text-foreground">
        {prompt.preview}
      </div>
    </button>
  );
}
