import { useEffect, useId, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";

interface SidebarTopicRenameProps {
  title: string;
  onSave: (title: string) => Promise<void>;
  onClose: () => void;
}

export function SidebarTopicRename({ title, onSave, onClose }: SidebarTopicRenameProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(title);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const savingRef = useRef(false);
  const composingRef = useRef(false);
  const errorId = useId();

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const save = async () => {
    const cleaned = value.trim();
    if (!cleaned || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setFailed(false);
    try {
      await onSave(cleaned);
      onClose();
    } catch {
      setFailed(true);
      inputRef.current?.focus();
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <form
      data-sidebar-topic-rename
      className="min-w-0 flex-1 py-0.5"
      aria-busy={saving}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        const composing = composingRef.current
          || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229;
        if (event.key === "Enter" && event.target === inputRef.current) {
          event.preventDefault();
          if (!composing) void save();
        } else if (event.key === "Escape" && !composing) {
          event.preventDefault();
          if (!savingRef.current) onClose();
        }
      }}
    >
      <div className="flex min-w-0 items-center gap-0.5">
        <Input
          ref={inputRef}
          className="h-7 min-w-0 flex-1 rounded-md border-sidebar-border bg-sidebar px-1.5 py-0 text-[13px]"
          aria-label={t("chat.renamePlaceholder")}
          aria-invalid={failed || undefined}
          aria-describedby={failed ? errorId : undefined}
          placeholder={t("chat.renamePlaceholder")}
          value={value}
          maxLength={160}
          readOnly={saving}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={() => { composingRef.current = false; }}
          onChange={(event) => {
            setValue(event.target.value);
            setFailed(false);
          }}
        />
        <button
          type="submit"
          aria-label={t("chat.renameSave")}
          disabled={saving || !value.trim()}
          className="touch-target inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-sidebar-foreground disabled:opacity-40"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            : <Check className="h-3.5 w-3.5" aria-hidden />}
        </button>
        <button
          type="button"
          aria-label={t("deleteConfirm.cancel")}
          disabled={saving}
          onClick={onClose}
          className="touch-target inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-sidebar-muted-foreground disabled:opacity-40"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      {failed ? (
        <p id={errorId} role="alert" className="px-1.5 py-1 text-xs text-destructive">
          {t("chat.renameFailed")}
        </p>
      ) : null}
    </form>
  );
}
