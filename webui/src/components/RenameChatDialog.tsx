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
  onCancel: () => void;
  onConfirm: (title: string) => void;
}

export function RenameChatDialog({
  open,
  title,
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
      <DialogContent className="max-w-sm rounded-[22px] border-border/70 bg-popover p-5 shadow-2xl">
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onConfirm(trimmed);
          }}
        >
          <DialogHeader className="text-left">
            <DialogTitle>{t("chat.renameTitle")}</DialogTitle>
            <DialogDescription>
              {t("chat.renameDescription")}
            </DialogDescription>
          </DialogHeader>
          <Input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t("chat.renamePlaceholder")}
            autoFocus
            maxLength={160}
          />
          <DialogFooter className="gap-2 sm:space-x-0">
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("deleteConfirm.cancel")}
            </Button>
            <Button type="submit" disabled={!trimmed}>
              {t("chat.renameSave")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
