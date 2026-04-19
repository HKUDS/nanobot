import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThreadComposerProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
  modelLabel?: string | null;
  variant?: "thread" | "hero";
}

export function ThreadComposer({
  onSend,
  disabled,
  placeholder,
  modelLabel = null,
  variant = "thread",
}: ThreadComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isHero = variant === "hero";
  const resolvedPlaceholder =
    placeholder ?? t("thread.composer.placeholderThread");

  useEffect(() => {
    if (disabled) return;
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [disabled]);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.style.height = "auto";
        el.focus();
      }
    });
  }, [disabled, onSend, value]);

  const onKeyDown: React.KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const onInput: React.FormEventHandler<HTMLTextAreaElement> = (e) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className={cn("w-full", isHero ? "px-0" : "px-1 pb-1.5 pt-1 sm:px-0")}
    >
      <div
        className={cn(
          "relative mx-auto flex w-full flex-col overflow-hidden transition-all duration-200",
          isHero
            ? "max-w-[40rem] rounded-[24px] border border-border/75 bg-card/72 shadow-[0_10px_30px_rgba(0,0,0,0.10)]"
            : "max-w-[49.5rem] rounded-[16px] border border-border/70 bg-card/55",
          "focus-within:bg-card/70 focus-within:ring-1 focus-within:ring-foreground/8",
          disabled && "opacity-60",
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onInput={onInput}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          aria-label={t("thread.composer.inputAria")}
          className={cn(
            "w-full resize-none bg-transparent",
            isHero
              ? "min-h-[96px] px-4 pb-2 pt-4 text-[15px] leading-6"
              : "min-h-[50px] px-4 pb-1.5 pt-3 text-sm",
            "placeholder:text-muted-foreground",
            "focus:outline-none focus-visible:outline-none",
            "disabled:cursor-not-allowed",
          )}
        />
        <div
          className={cn(
            "flex items-center justify-between gap-2",
            isHero ? "px-3.5 pb-3.5" : "px-3 pb-2",
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            {modelLabel ? (
              <span
                title={modelLabel}
                className={cn(
                  "inline-flex min-w-0 items-center gap-1.5 rounded-full border px-2.5 py-1",
                  "border-foreground/10 bg-foreground/[0.035] font-medium text-foreground/80",
                  isHero ? "text-[11px]" : "text-[10.5px]",
                )}
              >
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 flex-none rounded-full bg-emerald-500/80"
                />
                <span className="truncate">{modelLabel}</span>
              </span>
            ) : null}
            <span className="hidden select-none text-[10.5px] text-muted-foreground/60 sm:inline">
              {t("thread.composer.sendHint")}
            </span>
          </div>
          <span className="sm:hidden" aria-hidden />
          <Button
            type="submit"
            size="icon"
            disabled={disabled || !value.trim()}
            aria-label={t("thread.composer.send")}
            className={cn(
              "rounded-full border border-border/70 bg-secondary/85 text-secondary-foreground shadow-none transition-transform hover:bg-accent",
              isHero ? "h-8.5 w-8.5" : "h-7.5 w-7.5",
              value.trim() && !disabled && "hover:scale-[1.03] active:scale-95",
            )}
          >
            <ArrowUp className={cn(isHero ? "h-4.5 w-4.5" : "h-4 w-4")} />
          </Button>
        </div>
      </div>
    </form>
  );
}
