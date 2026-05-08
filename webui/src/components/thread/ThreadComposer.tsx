import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Activity,
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  History,
  ImageIcon,
  Loader2,
  Plus,
  RotateCw,
  Sparkles,
  Square,
  SquarePen,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  useAttachedImages,
  type AttachedImage,
  type AttachmentError,
  MAX_IMAGES_PER_MESSAGE,
} from "@/hooks/useAttachedImages";
import { useClipboardAndDrop } from "@/hooks/useClipboardAndDrop";
import type { SendImage, SendOptions } from "@/hooks/useNanobotStream";
import type { SlashCommand } from "@/lib/types";
import { cn } from "@/lib/utils";

/** ``<input accept>``: aligned with the server's MIME whitelist. SVG is
 * deliberately excluded to avoid an embedded-script XSS surface. */
const ACCEPT_ATTR = "image/png,image/jpeg,image/webp,image/gif";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface ThreadComposerProps {
  onSend: (content: string, images?: SendImage[], options?: SendOptions) => void;
  disabled?: boolean;
  placeholder?: string;
  isStreaming?: boolean;
  modelLabel?: string | null;
  variant?: "thread" | "hero";
  slashCommands?: SlashCommand[];
  imageMode?: boolean;
  onImageModeChange?: (enabled: boolean) => void;
  onStop?: () => void;
}

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  "book-open": BookOpen,
  "circle-help": CircleHelp,
  history: History,
  "rotate-cw": RotateCw,
  sparkles: Sparkles,
  square: Square,
  "square-pen": SquarePen,
  "undo-2": Undo2,
};

type ImageAspectRatio = "auto" | "1:1" | "3:4" | "9:16" | "4:3" | "16:9";

const IMAGE_ASPECT_RATIOS: ImageAspectRatio[] = ["auto", "1:1", "3:4", "9:16", "4:3", "16:9"];

function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

function scrollNearestOverflowParent(target: EventTarget | null, deltaY: number) {
  if (!(target instanceof Element) || deltaY === 0) return;
  let el: HTMLElement | null = target.parentElement;
  while (el) {
    const style = window.getComputedStyle(el);
    const canScroll = /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight;
    if (canScroll) {
      el.scrollTop += deltaY;
      return;
    }
    el = el.parentElement;
  }
}

export function ThreadComposer({
  onSend,
  disabled,
  placeholder,
  isStreaming = false,
  modelLabel = null,
  variant = "thread",
  slashCommands = [],
  imageMode: controlledImageMode,
  onImageModeChange,
  onStop,
}: ThreadComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [slashMenuDismissed, setSlashMenuDismissed] = useState(false);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const [uncontrolledImageMode, setUncontrolledImageMode] = useState(false);
  const [imageAspectRatio, setImageAspectRatio] = useState<ImageAspectRatio>("auto");
  const [aspectMenuOpen, setAspectMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const aspectControlRef = useRef<HTMLDivElement>(null);
  const chipRefs = useRef(new Map<string, HTMLButtonElement>());
  const isHero = variant === "hero";
  const imageMode = controlledImageMode ?? uncontrolledImageMode;
  const setImageMode = useCallback(
    (enabled: boolean) => {
      if (controlledImageMode === undefined) {
        setUncontrolledImageMode(enabled);
      }
      onImageModeChange?.(enabled);
    },
    [controlledImageMode, onImageModeChange],
  );
  const resolvedPlaceholder = isStreaming
    ? t("thread.composer.placeholderStreaming")
    : imageMode
      ? t("thread.composer.imageMode.placeholder")
      : placeholder ?? t("thread.composer.placeholderThread");

  const { images, enqueue, remove, clear, encoding, full } =
    useAttachedImages();

  const formatRejection = useCallback(
    (reason: AttachmentError): string => {
      const key = `thread.composer.imageRejected.${reason}`;
      return t(key, { max: MAX_IMAGES_PER_MESSAGE });
    },
    [t],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const { rejected } = enqueue(files);
      if (rejected.length > 0) {
        setInlineError(formatRejection(rejected[0].reason));
      } else {
        setInlineError(null);
      }
    },
    [enqueue, formatRejection],
  );

  const {
    isDragging,
    onPaste,
    onDragEnter,
    onDragOver,
    onDragLeave,
    onDrop,
  } = useClipboardAndDrop(addFiles);

  useEffect(() => {
    if (disabled) return;
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [disabled]);

  const readyImages = useMemo(
    () => images.filter((img): img is AttachedImage & { dataUrl: string } =>
      img.status === "ready" && typeof img.dataUrl === "string",
    ),
    [images],
  );
  const hasErrors = images.some((img) => img.status === "error");

  const canSend =
    !disabled
    && !encoding
    && !hasErrors
    && (value.trim().length > 0 || readyImages.length > 0);

  const slashQuery = useMemo(() => {
    if (disabled || slashMenuDismissed || !value.startsWith("/")) return null;
    const commandToken = value.slice(1);
    if (/\s/.test(commandToken)) return null;
    return commandToken.toLowerCase();
  }, [disabled, slashMenuDismissed, value]);

  const filteredSlashCommands = useMemo(() => {
    if (slashQuery === null) return [];
    return slashCommands
      .filter((command) => {
        const haystack = [
          command.command,
          command.title,
          command.description,
          command.argHint ?? "",
          t(`thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.title`, {
            defaultValue: "",
          }),
          t(`thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.description`, {
            defaultValue: "",
          }),
        ].join(" ").toLowerCase();
        return haystack.includes(slashQuery);
      })
      .slice(0, 8);
  }, [slashCommands, slashQuery, t]);

  const showSlashMenu = filteredSlashCommands.length > 0;

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [slashQuery]);

  useEffect(() => {
    if (selectedCommandIndex >= filteredSlashCommands.length) {
      setSelectedCommandIndex(0);
    }
  }, [filteredSlashCommands.length, selectedCommandIndex]);

  useEffect(() => {
    if (!aspectMenuOpen) return;

    const closeOnPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && aspectControlRef.current?.contains(target)) return;
      setAspectMenuOpen(false);
    };
    const closeOnKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAspectMenuOpen(false);
        textareaRef.current?.focus();
      }
    };
    const closeOnScroll = () => setAspectMenuOpen(false);
    const closeOnWheel = (event: WheelEvent) => {
      setAspectMenuOpen(false);
      scrollNearestOverflowParent(event.target, event.deltaY);
    };

    document.addEventListener("pointerdown", closeOnPointerDown, true);
    document.addEventListener("keydown", closeOnKeyDown);
    document.addEventListener("scroll", closeOnScroll, true);
    document.addEventListener("wheel", closeOnWheel, { capture: true, passive: true });
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown, true);
      document.removeEventListener("keydown", closeOnKeyDown);
      document.removeEventListener("scroll", closeOnScroll, true);
      document.removeEventListener("wheel", closeOnWheel, true);
    };
  }, [aspectMenuOpen]);

  const resizeTextarea = useCallback(() => {
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
      el.focus();
    });
  }, []);

  const chooseSlashCommand = useCallback(
    (command: SlashCommand) => {
      setValue(command.argHint ? `${command.command} ` : command.command);
      setSlashMenuDismissed(true);
      setInlineError(null);
      resizeTextarea();
    },
    [resizeTextarea],
  );

  const submit = useCallback(() => {
    if (!canSend) return;
    const trimmed = value.trim();
    // Share the same normalized ``data:`` URL with both the wire payload and
    // the optimistic bubble preview: data URLs are self-contained (no blob
    // lifetime, safe under React StrictMode double-mount) and keep the
    // bubble in sync with whatever the backend actually sees.
    const payload: SendImage[] | undefined =
      readyImages.length > 0
        ? readyImages.map((img) => ({
            media: {
              data_url: img.dataUrl,
              name: img.file.name,
            },
            preview: { url: img.dataUrl, name: img.file.name },
          }))
        : undefined;
    const options: SendOptions | undefined = imageMode
      ? {
          imageGeneration: {
            enabled: true,
            aspect_ratio: imageAspectRatio === "auto" ? null : imageAspectRatio,
          },
        }
      : undefined;
    onSend(trimmed, payload, options);
    setValue("");
    setInlineError(null);
    // Bubble owns the data URL copy; safe to revoke every staged blob
    // preview here without affecting the rendered message.
    clear();
    setSlashMenuDismissed(false);
    resizeTextarea();
  }, [canSend, clear, imageAspectRatio, imageMode, onSend, readyImages, resizeTextarea, value]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCommandIndex((idx) => (idx + 1) % filteredSlashCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedCommandIndex(
          (idx) => (idx - 1 + filteredSlashCommands.length) % filteredSlashCommands.length,
        );
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        chooseSlashCommand(filteredSlashCommands[selectedCommandIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashMenuDismissed(true);
        return;
      }
    }
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

  const onFilePick: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    addFiles(files);
  };

  const removeChip = useCallback(
    (id: string) => {
      const { nextFocusId } = remove(id);
      setInlineError(null);
      requestAnimationFrame(() => {
        const el = nextFocusId ? chipRefs.current.get(nextFocusId) : null;
        if (el) {
          el.focus();
        } else {
          textareaRef.current?.focus();
        }
      });
    },
    [remove],
  );

  const onChipKey = useCallback(
    (id: string) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
      if (
        e.key === "Delete" ||
        e.key === "Backspace" ||
        e.key === "Enter" ||
        e.key === " "
      ) {
        e.preventDefault();
        removeChip(id);
      }
    },
    [removeChip],
  );

  const attachButtonDisabled = disabled || full;
  const showStopButton = isStreaming && !!onStop;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn("relative w-full", isHero ? "px-0" : "px-1 pb-1.5 pt-1 sm:px-0")}
    >
      {showSlashMenu ? (
        <SlashCommandPalette
          commands={filteredSlashCommands}
          selectedIndex={selectedCommandIndex}
          isHero={isHero}
          onHover={setSelectedCommandIndex}
          onChoose={chooseSlashCommand}
        />
      ) : null}
      <div
        className={cn(
          "relative mx-auto flex w-full flex-col overflow-visible transition-all duration-200",
          isHero
            ? "max-w-[58rem] rounded-[28px] border border-black/[0.035] bg-card shadow-[0_20px_55px_rgba(15,23,42,0.08)] dark:border-white/[0.06] dark:shadow-[0_24px_55px_rgba(0,0,0,0.34)]"
            : "max-w-[49.5rem] rounded-[22px] border border-black/[0.035] bg-card shadow-[0_12px_30px_rgba(15,23,42,0.07)] dark:border-white/[0.06] dark:shadow-[0_16px_34px_rgba(0,0,0,0.28)]",
          "focus-within:ring-1 focus-within:ring-foreground/8",
          disabled && "opacity-60",
          isDragging && "ring-2 ring-primary/40 motion-reduce:ring-0 motion-reduce:border-primary",
        )}
      >
        {images.length > 0 ? (
          <div
            className="flex flex-wrap gap-2 px-3 pt-3"
            aria-label={t("thread.composer.attachImage")}
          >
            {images.map((img) => (
              <AttachmentChip
                key={img.id}
                image={img}
                labelRemove={t("thread.composer.remove")}
                labelEncoding={t("thread.composer.encoding")}
                normalizedHint={(orig, current) =>
                  t("thread.composer.normalizedSizeHint", {
                    orig: formatBytes(orig),
                    current: formatBytes(current),
                  })
                }
                formatError={formatRejection}
                onRemove={() => removeChip(img.id)}
                onKeyDown={onChipKey(img.id)}
                registerRef={(el) => {
                  if (el) chipRefs.current.set(img.id, el);
                  else chipRefs.current.delete(img.id);
                }}
              />
            ))}
          </div>
        ) : null}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSlashMenuDismissed(false);
          }}
          onInput={onInput}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          rows={1}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          aria-label={t("thread.composer.inputAria")}
          className={cn(
            "w-full resize-none bg-transparent",
            isHero
              ? "min-h-[78px] px-5 pb-2 pt-5 text-[15px] leading-6"
              : "min-h-[50px] px-4 pb-1.5 pt-3 text-[13.5px] leading-5",
            "placeholder:text-muted-foreground/70",
            "focus:outline-none focus-visible:outline-none",
            "disabled:cursor-not-allowed",
          )}
        />
        {inlineError ? (
          <div
            role="alert"
            className={cn(
              "mx-3 mb-1 rounded-md border border-destructive/40 bg-destructive/8 px-2.5 py-1",
              "text-[11.5px] font-medium text-destructive",
            )}
          >
            {inlineError}
          </div>
        ) : null}
        <div
          className={cn(
            "flex items-center justify-between gap-2",
            isHero ? "px-4 pb-4" : "px-3 pb-2",
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_ATTR}
              multiple
              hidden
              onChange={onFilePick}
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              disabled={attachButtonDisabled}
              aria-label={t("thread.composer.attachImage")}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "rounded-full text-muted-foreground hover:text-foreground",
                isHero
                  ? "h-9 w-9 border border-border/55 bg-card shadow-[0_2px_8px_rgba(15,23,42,0.05)] hover:bg-card"
                  : "h-7.5 w-7.5 border border-border/55 bg-card shadow-[0_2px_8px_rgba(15,23,42,0.05)] hover:bg-card",
              )}
            >
              <Plus className={cn(isHero ? "h-5 w-5" : "h-4 w-4")} />
            </Button>
            <div ref={aspectControlRef} className="relative flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                disabled={disabled}
                aria-pressed={imageMode}
                aria-label={t("thread.composer.imageMode.toggle")}
                onClick={() => {
                  setImageMode(!imageMode);
                  setAspectMenuOpen(false);
                  textareaRef.current?.focus();
                }}
                className={cn(
                  "rounded-full border border-border/55 px-2.5 font-medium shadow-[0_2px_8px_rgba(15,23,42,0.04)]",
                  isHero ? "h-9 text-[12px]" : "h-7.5 text-[10.5px]",
                  imageMode
                    ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/12"
                    : "bg-card text-muted-foreground hover:bg-card hover:text-foreground",
                )}
              >
                <ImageIcon className={cn("mr-1.5", isHero ? "h-4 w-4" : "h-3.5 w-3.5")} />
                {t("thread.composer.imageMode.label")}
              </Button>
              {imageMode ? (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={disabled}
                  aria-haspopup="listbox"
                  aria-expanded={aspectMenuOpen}
                  aria-label={t("thread.composer.imageMode.aspectAria")}
                  onClick={() => setAspectMenuOpen((open) => !open)}
                  className={cn(
                    "rounded-full border border-border/55 bg-card px-2.5 font-medium text-foreground/80 shadow-[0_2px_8px_rgba(15,23,42,0.04)] hover:bg-card",
                    isHero ? "h-9 text-[12px]" : "h-7.5 text-[10.5px]",
                  )}
                >
                  <span>{t(`thread.composer.imageMode.aspect.${imageAspectRatio.replace(":", "_")}`)}</span>
                  <ChevronDown className={cn("ml-1.5", isHero ? "h-3.5 w-3.5" : "h-3 w-3")} />
                </Button>
              ) : null}
              {imageMode && aspectMenuOpen ? (
                <ImageAspectMenu
                  selected={imageAspectRatio}
                  isHero={isHero}
                  onSelect={(ratio) => {
                    setImageAspectRatio(ratio);
                    setAspectMenuOpen(false);
                    textareaRef.current?.focus();
                  }}
                />
              ) : null}
            </div>
            {modelLabel ? (
              <span
                title={modelLabel}
                className={cn(
                  "inline-flex min-w-0 items-center gap-1.5 rounded-full border px-2.5 py-1",
                  "border-foreground/10 bg-foreground/[0.035] font-medium text-foreground/80",
                  isHero
                    ? "max-w-[13rem] text-[12px] shadow-[0_2px_8px_rgba(15,23,42,0.04)]"
                    : "max-w-[10rem] text-[10.5px] shadow-[0_2px_8px_rgba(15,23,42,0.035)]",
                )}
              >
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 flex-none rounded-full bg-emerald-500/80"
                />
                <span className="truncate">{modelLabel}</span>
              </span>
            ) : null}
            {!isHero ? (
              <span className="hidden select-none text-[10.5px] text-muted-foreground/60 sm:inline">
                {t("thread.composer.sendHint")}
              </span>
            ) : null}
          </div>
          <span className={cn(isHero ? "hidden" : "sm:hidden")} aria-hidden />
          <Button
            type={showStopButton ? "button" : "submit"}
            size="icon"
            disabled={showStopButton ? disabled : !canSend}
            aria-label={showStopButton ? t("thread.composer.stop") : t("thread.composer.send")}
            onClick={showStopButton ? onStop : undefined}
            className={cn(
              "rounded-full transition-transform",
              showStopButton
                ? "border border-border/70 bg-card text-foreground/85 shadow-[0_3px_10px_rgba(15,23,42,0.08)] hover:bg-muted/65 hover:text-foreground disabled:text-muted-foreground/50"
                : isHero
                  ? "border border-foreground bg-foreground text-background shadow-[0_4px_12px_rgba(15,23,42,0.20)] hover:bg-foreground/90 disabled:border-foreground/35 disabled:bg-foreground/35 disabled:text-background/80"
                  : "border border-foreground bg-foreground text-background shadow-[0_3px_10px_rgba(15,23,42,0.18)] hover:bg-foreground/90 disabled:border-foreground/35 disabled:bg-foreground/35 disabled:text-background/80",
              isHero ? "" : "h-7.5 w-7.5",
              (canSend || showStopButton) && "hover:scale-[1.03] active:scale-95",
            )}
          >
            {showStopButton ? (
              <Square className={cn("fill-current stroke-current", isHero ? "h-3 w-3" : "h-2.5 w-2.5")} />
            ) : isStreaming ? (
              <Loader2 className={cn(isHero ? "h-4.5 w-4.5" : "h-4 w-4", "animate-spin")} />
            ) : (
              <ArrowUp className={cn(isHero ? "h-4.5 w-4.5" : "h-4 w-4")} />
            )}
          </Button>
        </div>
      </div>
    </form>
  );
}

interface SlashCommandPaletteProps {
  commands: SlashCommand[];
  selectedIndex: number;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (command: SlashCommand) => void;
}

function ImageAspectMenu({
  selected,
  isHero,
  onSelect,
}: {
  selected: ImageAspectRatio;
  isHero: boolean;
  onSelect: (ratio: ImageAspectRatio) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.imageMode.aspectAria")}
      className={cn(
        "absolute left-0 z-30 w-44 overflow-hidden rounded-[16px] border",
        isHero ? "top-full mt-2" : "bottom-full mb-2",
        "border-border/65 bg-popover p-1.5 text-popover-foreground shadow-[0_16px_45px_rgba(15,23,42,0.16)]",
        "dark:border-white/10 dark:shadow-[0_18px_45px_rgba(0,0,0,0.42)]",
        isHero ? "text-[12px]" : "text-[11.5px]",
      )}
    >
      <div className="px-2 pb-1 pt-1 font-medium text-muted-foreground/70">
        {t("thread.composer.imageMode.aspectLabel")}
      </div>
      {IMAGE_ASPECT_RATIOS.map((ratio) => {
        const label = t(`thread.composer.imageMode.aspect.${ratio.replace(":", "_")}`);
        return (
          <button
            key={ratio}
            type="button"
            role="option"
            aria-selected={selected === ratio}
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(ratio);
            }}
            className={cn(
              "flex w-full items-center justify-between rounded-[11px] px-2.5 py-2 text-left transition-colors",
              selected === ratio
                ? "bg-primary/10 text-foreground"
                : "text-foreground/86 hover:bg-accent/55",
            )}
          >
            <span>{label}</span>
            {selected === ratio ? <Check className="h-3.5 w-3.5 text-primary" /> : null}
          </button>
        );
      })}
    </div>
  );
}

function SlashCommandPalette({
  commands,
  selectedIndex,
  isHero,
  onHover,
  onChoose,
}: SlashCommandPaletteProps) {
  const { t } = useTranslation();
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.slash.ariaLabel")}
      className={cn(
        "absolute bottom-full left-1/2 z-30 mb-2 max-h-[22rem] w-[calc(100%-0.5rem)] -translate-x-1/2 overflow-hidden rounded-[18px] border",
        "border-border/65 bg-popover p-1.5 text-popover-foreground shadow-[0_18px_55px_rgba(15,23,42,0.18)]",
        "dark:border-white/10 dark:shadow-[0_22px_55px_rgba(0,0,0,0.45)]",
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div className="px-2 pb-1 pt-1 text-[11px] font-medium tracking-[0.08em] text-muted-foreground/70">
        {t("thread.composer.slash.label")}
      </div>
      <div className="max-h-[18rem] overflow-y-auto pr-0.5">
        {commands.map((command, index) => {
          const Icon = COMMAND_ICONS[command.icon] ?? CircleHelp;
          const selected = index === selectedIndex;
          const commandKey = slashCommandI18nKey(command.command);
          const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
            defaultValue: command.title,
          });
          const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
            defaultValue: command.description,
          });
          return (
            <button
              key={command.command}
              type="button"
              role="option"
              aria-selected={selected}
              onMouseEnter={() => onHover(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onChoose(command);
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-[13px] px-3 py-2.5 text-left transition-colors",
                selected
                  ? "bg-primary/10 text-foreground"
                  : "text-foreground/86 hover:bg-accent/55",
              )}
            >
              <span
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border",
                  selected
                    ? "border-primary/25 bg-primary/12 text-primary"
                    : "border-border/65 bg-muted/45 text-muted-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="font-mono text-[13px] font-semibold text-foreground">
                    {command.command}
                  </span>
                  {command.argHint ? (
                    <span className="font-mono text-[12px] text-muted-foreground">
                      {command.argHint}
                    </span>
                  ) : null}
                  <span className="truncate text-[13px] font-medium">
                    {title}
                  </span>
                </span>
                <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">
                  {description}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-2 px-2 pt-1.5 text-[10.5px] text-muted-foreground/70">
        <span>{t("thread.composer.slash.navigateHint")}</span>
        <span>{t("thread.composer.slash.selectHint")}</span>
        <span>{t("thread.composer.slash.closeHint")}</span>
      </div>
    </div>
  );
}

interface AttachmentChipProps {
  image: AttachedImage;
  labelRemove: string;
  labelEncoding: string;
  normalizedHint: (origBytes: number, currentBytes: number) => string;
  formatError: (reason: AttachmentError) => string;
  onRemove: () => void;
  onKeyDown: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  registerRef: (el: HTMLButtonElement | null) => void;
}

function AttachmentChip({
  image,
  labelRemove,
  labelEncoding,
  normalizedHint,
  formatError,
  onRemove,
  onKeyDown,
  registerRef,
}: AttachmentChipProps) {
  const sizeLabel =
    image.status === "ready" && image.normalized && image.encodedBytes
      ? normalizedHint(image.file.size, image.encodedBytes)
      : formatBytes(image.file.size);
  const tone =
    image.status === "error"
      ? "border-destructive/40 bg-destructive/5 text-destructive"
      : "border-border/70 bg-muted/60";

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-[12px] border px-2 py-1.5",
        "transition-colors motion-reduce:transition-none",
        tone,
      )}
      data-testid="composer-chip"
    >
      <div className="relative h-10 w-10 overflow-hidden rounded-md bg-background">
        {image.previewUrl ? (
          <img
            src={image.previewUrl}
            alt=""
            aria-hidden
            loading="eager"
            draggable={false}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <ImageIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
          </div>
        )}
        {image.status === "encoding" ? (
          <div
            className="absolute inset-0 flex items-center justify-center bg-background/60"
            aria-label={labelEncoding}
          >
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          </div>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col text-[11.5px] leading-4">
        <span className="truncate max-w-[14rem] font-medium" title={image.file.name}>
          {image.file.name}
        </span>
        <span className="truncate text-muted-foreground">
          {image.status === "error" && image.error
            ? formatError(image.error)
            : sizeLabel}
        </span>
      </div>
      <button
        type="button"
        ref={registerRef}
        onClick={onRemove}
        onKeyDown={onKeyDown}
        aria-label={labelRemove}
        className={cn(
          "ml-1 grid h-5 w-5 flex-none place-items-center rounded-full",
          "text-muted-foreground/80 hover:bg-foreground/8 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
