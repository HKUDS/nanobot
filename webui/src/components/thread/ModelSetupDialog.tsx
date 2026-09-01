import { useRef } from "react";
import { Check, Cloud, KeyRound, Laptop } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { ModelSetupAvailability, ModelSetupIntent } from "@/lib/model-setup";

const SETUP_OPTIONS = [
  {
    intent: "account",
    icon: Cloud,
    titleKey: "thread.composer.modelSetup.account.title",
    title: "Connect an account",
    descriptionKey: "thread.composer.modelSetup.account.description",
    description: "Use a supported AI subscription.",
  },
  {
    intent: "apiKey",
    icon: KeyRound,
    titleKey: "thread.composer.modelSetup.apiKey.title",
    title: "Use an API key",
    descriptionKey: "thread.composer.modelSetup.apiKey.description",
    description: "Bring a key from your preferred provider.",
  },
  {
    intent: "local",
    icon: Laptop,
    titleKey: "thread.composer.modelSetup.local.title",
    title: "Run locally",
    descriptionKey: "thread.composer.modelSetup.local.description",
    description: "Connect Ollama, LM Studio, or vLLM.",
  },
] as const;

export function ModelSetupDialog({
  availability,
  open,
  onOpenChange,
  onReturnFocus,
  onSelect,
}: {
  availability: ModelSetupAvailability;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReturnFocus: () => void;
  onSelect: (intent: ModelSetupIntent) => void;
}) {
  const { t } = useTranslation();
  const selectedRef = useRef(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) selectedRef.current = false;
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="max-w-md gap-5 p-5 sm:p-6"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!selectedRef.current) onReturnFocus();
          selectedRef.current = false;
        }}
      >
        <DialogHeader className="pr-7">
          <DialogTitle className="text-[18px] leading-6">
            {t("thread.composer.modelSetup.title", { defaultValue: "Choose your AI" })}
          </DialogTitle>
          <DialogDescription className="leading-5">
            {t("thread.composer.modelSetup.description", {
              defaultValue: "Pick a starting point. You can change models at any time.",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {SETUP_OPTIONS.map((option) => {
            const Icon = option.icon;
            const ready = availability[option.intent];
            return (
              <button
                key={option.intent}
                type="button"
                aria-label={t(option.titleKey, { defaultValue: option.title })}
                onClick={() => {
                  selectedRef.current = true;
                  onSelect(option.intent);
                }}
                className={cn(
                  "group flex min-h-[68px] w-full items-center gap-3 rounded-control border border-border/55 bg-background px-3.5 py-3 text-left",
                  "transition-[background-color,border-color,transform] duration-150 ease-out hover:border-border hover:bg-muted/45 active:scale-[0.99]",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45",
                )}
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted/70 text-foreground/75 transition-colors group-hover:bg-background">
                  <Icon className="h-[17px] w-[17px]" strokeWidth={1.8} aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-semibold leading-5 text-foreground">
                    {t(option.titleKey, { defaultValue: option.title })}
                  </span>
                  <span className="mt-0.5 block text-[12px] leading-[18px] text-muted-foreground">
                    {t(option.descriptionKey, { defaultValue: option.description })}
                  </span>
                </span>
                {ready ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                    <Check className="h-3 w-3" strokeWidth={2.2} aria-hidden />
                    {t("thread.composer.modelSetup.ready", { defaultValue: "Ready" })}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
