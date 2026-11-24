import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ToastProvider, useToast } from "@/components/ui/toast";

function ToastActions({ stack, longTitle, modal }: { stack: boolean; longTitle: boolean; modal: boolean }) {
  const { t } = useTranslation();
  const show = useToast();
  const [result, setResult] = useState<"undone" | "committed" | null>(null);

  const play = () => {
    setResult(null);
    show?.({
      message: t("toast.pendingDeleteSingle"),
      detail: longTitle ? "Research notes: cross-platform layout and keyboard accessibility verification" : "Research notes",
      tone: "pending",
      action: { label: t("toast.undo"), run: () => setResult("undone") },
      onExpire: () => setResult("committed"),
    });
    if (stack) show?.({ message: t("fileActions.copied"), tone: "success" });
  };

  return <main className="mx-auto max-w-3xl space-y-4 px-4" style={{ paddingTop: "8rem" }}>
    <h1>Toast fixtures</h1>
    <div className="flex flex-wrap gap-3">
      <Button variant="outline" onClick={play}>Play timing</Button>
      {modal && <>
        {/* The app also has a live region outside the modal; Radix then hides the toast viewport itself. */}
        <span aria-live="polite" className="sr-only" />
        <Sheet>
          <SheetTrigger asChild><Button variant="outline">Open sheet</Button></SheetTrigger>
          <SheetContent>
            <SheetTitle>Navigation sheet</SheetTitle>
            <SheetDescription>Toast actions are not reachable while this sheet is open.</SheetDescription>
          </SheetContent>
        </Sheet>
      </>}
    </div>
    {result === "undone" && <p>Undo applied</p>}
    {result === "committed" && <p>Simulated delete committed</p>}
  </main>;
}

function ArchivePreview() {
  const { t } = useTranslation();
  const show = useToast();
  useEffect(() => {
    show?.({
      message: t("toast.archivedSingle"),
      detail: "查找 Shell 完整命令",
      tone: "success",
      persistent: true,
      dedupeKey: "archive-preview",
      action: { label: t("toast.undo"), run: () => {} },
    });
  }, [show, t]);
  return null;
}

export function ToastFixture({ parameters }: { parameters: URLSearchParams }) {
  document.documentElement.classList.toggle("dark", parameters.has("dark"));
  return <ToastProvider>
    {parameters.get("scene") === "archive" ? <ArchivePreview /> : <ToastActions stack={parameters.get("scene") === "stack"} longTitle={parameters.has("long-title")} modal={parameters.has("modal")} />}
  </ToastProvider>;
}
