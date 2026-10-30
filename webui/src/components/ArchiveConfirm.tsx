import { Archive, ArchiveRestore } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export function ArchiveConfirm({
  count,
  archive,
  onCancel,
  onConfirm,
}: {
  count: number;
  archive: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const Icon = archive ? Archive : ArchiveRestore;
  const titleKey = archive
    ? count > 1 ? "archiveConfirm.titleMany" : "archiveConfirm.title"
    : count > 1 ? "archiveConfirm.unarchiveTitleMany" : "archiveConfirm.unarchiveTitle";
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <AlertDialogContent
        className="w-[min(calc(100vw-2rem),24rem)] gap-0 p-5 text-center"
        onEscapeKeyDown={(event) => event.stopPropagation()}
      >
        <AlertDialogHeader className="items-center space-y-0 text-center">
          <Icon className="mb-4 h-6 w-6 text-muted-foreground" strokeWidth={1.8} aria-hidden />
          <AlertDialogTitle className="text-center text-[20px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
            {t(titleKey, { count })}
          </AlertDialogTitle>
          <AlertDialogDescription className="mt-3 max-w-[17rem] text-center text-[14px] leading-6 text-muted-foreground">
            {t(archive ? "archiveConfirm.description" : "archiveConfirm.unarchiveDescription")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="mt-6 !grid grid-cols-1 gap-2 sm:grid-cols-2">
          <AlertDialogCancel onClick={onCancel} className="mt-0 w-full min-w-0">
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="w-full min-w-0 !whitespace-normal bg-foreground text-center text-background hover:bg-foreground/90"
          >
            {t(archive ? "chat.archive" : "chat.unarchive")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
