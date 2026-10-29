import { useEffect, useId, useRef, useState, type CSSProperties, type Dispatch, type SetStateAction } from "react";
import { ArrowUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { MAX_READING_SIZE, MIN_READING_SIZE, type LocalPreferences, type ReadingTextSize } from "@/lib/local-preferences";

export function ReadingSettings({ preferences, onChange }: {
  preferences: LocalPreferences;
  onChange: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const custom = preferences.readingTextSize === "custom";
  const [draft, setDraft] = useState(String(preferences.customReadingTextSize));
  const [hintOpen, setHintOpen] = useState(false);
  const [showError, setShowError] = useState(false);
  const hint = t(showError ? "settings.appearance.customInvalid" : "settings.appearance.customRange", {
    min: MIN_READING_SIZE, max: MAX_READING_SIZE, size: preferences.customReadingTextSize,
  });
  useEffect(() => {
    setDraft(String(preferences.customReadingTextSize));
    setShowError(false);
    // A preset selected in another tab ends an unfinished custom edit.
    if (!custom) {
      setHintOpen(false);
      if (document.activeElement === inputRef.current) inputRef.current?.blur();
    }
  }, [preferences.customReadingTextSize, custom]);

  const commitDraft = () => {
    if (!custom) return true;
    const value = draft.trim() ? Number(draft) : preferences.customReadingTextSize;
    // Native number inputs expose unfinished values such as "-" as an empty string.
    if (inputRef.current?.validity.badInput || !Number.isInteger(value) || value < MIN_READING_SIZE || value > MAX_READING_SIZE) {
      setShowError(true);
      setHintOpen(true);
      return false;
    }
    setDraft(String(value));
    setShowError(false);
    setHintOpen(false);
    onChange((previous) => ({ ...previous, customReadingTextSize: value }));
    return true;
  };

  return <div className="appearance-reading-card">
    <div className="appearance-reading-controls">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-control-label" id={`${id}-label`}>
          <SettingsHint description={t("settings.appearance.readingHelp")}>{t("settings.rows.readingTextSize")}</SettingsHint>
        </span>
        <div className="appearance-size-options">
          <SegmentedControl<ReadingTextSize>
            mode="radio"
            value={preferences.readingTextSize}
            ariaLabel={t("settings.rows.readingTextSize")}
            className="appearance-size-presets gap-0 p-0.5"
            itemClassName="flex items-center justify-center p-0"
            options={([
              ["small", "text-[12px]"], ["standard", "text-[16px]"], ["large", "text-[20px]"],
            ] as const).map(([value, size]) => ({
              value,
              label: <span aria-hidden className={size}>A</span>,
              ariaLabel: t(`settings.readingTextSize.${value}`),
              tooltip: t(`settings.readingTextSize.${value}`),
            }))}
            onChange={(readingTextSize) => onChange((previous) => ({ ...previous, readingTextSize }))}
          />
          <TooltipProvider>
            <Tooltip open={hintOpen} onOpenChange={(open) => {
              // Keep guidance visible while typing, including pointer/touch focus.
              if (open || document.activeElement !== inputRef.current) setHintOpen(open);
            }}>
              <TooltipTrigger asChild>
                <label className="appearance-custom-option" htmlFor={`${id}-custom`} data-selected={custom} data-invalid={showError}>
                  <span className="appearance-custom-label">{t("settings.appearance.custom")}</span>
                  <span className="appearance-custom-value">
                    <Input ref={inputRef} id={`${id}-custom`} type="number" inputMode="numeric" min={MIN_READING_SIZE} max={MAX_READING_SIZE} step={1}
                      className="appearance-size-input h-[calc(var(--appearance-preset-size)-16px)] w-[3ch] border-0 bg-transparent p-0 text-right text-ui-label tabular-nums focus-visible:ring-0"
                      aria-label={t("settings.appearance.customSize")}
                      aria-describedby={`${id}-range`}
                      aria-invalid={showError || undefined}
                      value={draft}
                      onFocus={(event) => {
                        event.currentTarget.select();
                        setHintOpen(true);
                        if (!custom) onChange((previous) => ({ ...previous, readingTextSize: "custom" }));
                      }}
                      onChange={(event) => {
                        const next = event.currentTarget.value;
                        setDraft(next);
                        setShowError(false);
                        const value = Number(next);
                        if (next.trim() && Number.isInteger(value) && value >= MIN_READING_SIZE && value <= MAX_READING_SIZE) {
                          onChange((previous) => ({ ...previous, readingTextSize: "custom", customReadingTextSize: value }));
                        }
                      }}
                      onBlur={(event) => {
                        if (!commitDraft()) event.preventDefault();
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") event.currentTarget.blur();
                        if (event.key === "Escape") {
                          event.preventDefault();
                          event.stopPropagation();
                          setDraft(String(preferences.customReadingTextSize));
                          setShowError(false);
                          setHintOpen(false);
                        }
                      }}
                    />
                    <span aria-hidden className="text-caption text-muted-foreground">px</span>
                  </span>
                </label>
              </TooltipTrigger>
              <TooltipContent side="top" align="end" sideOffset={10}
                className={`max-w-[min(20rem,calc(100vw-2rem))] whitespace-pre-line leading-relaxed ${showError ? "text-destructive" : ""}`}>
                {hint}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
      <span className="sr-only" id={`${id}-range`} aria-live="polite">{hint}</span>
    </div>
    <div className="reading-typography appearance-reading-preview"
      data-reading-text-size={preferences.readingTextSize}
      style={{ "--custom-reading-size": `${preferences.customReadingTextSize}px` } as CSSProperties}>
      <div className="mb-4 flex items-center gap-2 text-caption font-medium text-foreground">
        <img src="/brand/nanobot_mark.svg" className="h-5 w-5" alt="" />nanobot
      </div>
      <div data-reading-preview-content>
        <MarkdownText>{t("settings.appearance.previewText")}</MarkdownText>
        <div className="mt-4 overflow-x-auto rounded-control bg-muted/60 px-4 py-3">
          <code className={`block font-mono text-code ${preferences.codeWrap ? "whitespace-pre-wrap break-words" : "whitespace-pre"}`}><span className="text-[color:var(--code-keyword)]">const</span>{' idea = '}<span className="text-[color:var(--code-string)]">{'"Hello, nanobot."'}</span>;</code>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-3 rounded-control border border-border/65 px-4 py-3 text-muted-foreground/80" aria-hidden>
        <span className="min-w-0 flex-1 text-composer">{t("settings.appearance.previewPlaceholder")}</span>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background"><ArrowUp className="h-4 w-4" /></span>
      </div>
    </div>
  </div>;
}
