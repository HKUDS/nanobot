import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface RenameChatDialogProps {
  open: boolean;
  title: string;
  dialogTitle?: string;
  description?: string;
  placeholder?: string;
  onCancel: () => void;
  onConfirm: (title: string) => void;
}

export function RenameChatDialog({
  open,
  title,
  dialogTitle,
  description,
  placeholder,
  onCancel,
  onConfirm,
}: RenameChatDialogProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(title);

  useEffect(() => {
    if (open) setValue(title);
  }, [open, title]);

  const trimmed = value.trim();

  return (
    <Dialog open={open} onOpenChange={(next) => {
      if (!next) onCancel();
    }}>
      <DialogContent className="max-w-sm rounded-[20px] p-5 sm:p-6">
        <form
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onConfirm(trimmed);
          }}
        >
          <DialogHeader className="space-y-1 text-left">
            <DialogTitle className="text-xl leading-tight">
              {dialogTitle ?? t("chat.renameTitle")}
            </DialogTitle>
            <DialogDescription className="leading-relaxed">
              {description ?? t("chat.renameDescription")}
            </DialogDescription>
          </DialogHeader>
          <Input
            className="h-11 rounded-xl border-border/80 bg-muted/20 px-3.5 text-[15px]"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder ?? t("chat.renamePlaceholder")}
            autoFocus
            maxLength={160}
          />
          <DialogFooter className="gap-2 pt-1 sm:space-x-0">
            <Button
              className="min-w-20 rounded-xl"
              type="button"
              variant="outline"
              onClick={onCancel}
            >
              {t("deleteConfirm.cancel")}
            </Button>
            <Button className="min-w-20 rounded-xl" type="submit" disabled={!trimmed}>
              {t("chat.renameSave")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
