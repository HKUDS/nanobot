import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

interface ThreadViewportProps {
  messages: UIMessage[];
  isStreaming: boolean;
  composer: ReactNode;
  emptyState?: ReactNode;
}

const NEAR_BOTTOM_PX = 48;

export function ThreadViewport({
  messages,
  isStreaming,
  composer,
  emptyState,
}: ThreadViewportProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const hasMessages = messages.length > 0;

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  useEffect(() => {
    if (!atBottom) return;
    scrollToBottom(!isStreaming);
  }, [messages, isStreaming, atBottom, scrollToBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      setAtBottom(distance < NEAR_BOTTOM_PX);
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          "absolute inset-0 overflow-y-auto scroll-smooth scrollbar-thin",
          "[&::-webkit-scrollbar]:w-1.5",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/30",
          "[&::-webkit-scrollbar-track]:bg-transparent",
        )}
      >
        {hasMessages ? (
          <div className="mx-auto flex min-h-full w-full max-w-[64rem] flex-col">
            <div className="flex-1 px-4 pb-20 pt-4">
              <div className="mx-auto w-full max-w-[49.5rem]">
                <ThreadMessages messages={messages} />
              </div>
            </div>

            <div className="sticky bottom-0 z-10 mt-auto bg-background">
              <div className="px-4 pb-3">
                {composer}
              </div>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex min-h-full w-full max-w-[72rem] flex-col px-4">
            <div className="flex w-full flex-1 items-center justify-center pb-[7vh] pt-8">
              <div className="flex w-full max-w-[58rem] flex-col gap-6">
                {emptyState}
                <div className="w-full">{composer}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-background to-transparent"
      />

      {!atBottom && (
        <Button
          variant="outline"
          size="icon"
          onClick={() => scrollToBottom(true)}
          className={cn(
            "absolute bottom-28 left-1/2 h-8 w-8 -translate-x-1/2 rounded-full shadow-md",
            "bg-background/90 backdrop-blur",
            "animate-in fade-in-0 zoom-in-95",
          )}
          aria-label={t("thread.scrollToBottom")}
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
