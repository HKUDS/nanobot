import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ExtensionsCatalog } from "@/components/extensions/ExtensionsCatalog";
import { cn } from "@/lib/utils";

interface ExtensionsViewProps {
  hostChromeInset?: boolean;
  onBackToChat: () => void;
}

export function ExtensionsView({
  hostChromeInset = false,
  onBackToChat,
}: ExtensionsViewProps) {
  const { t } = useTranslation();

  return (
    <main className="h-full min-w-0 overflow-y-auto bg-settings-canvas [scrollbar-gutter:stable]">
      <div
        className={cn(
          "mx-auto w-full max-w-[920px] px-4 py-6 sm:px-8 sm:py-8 lg:py-12",
          hostChromeInset && "pt-[4.25rem] sm:pt-[4.25rem] lg:pt-[4.75rem]",
        )}
      >
        <button
          type="button"
          onClick={onBackToChat}
          className="touch-target mb-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground lg:hidden"
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
          {t("extensions.backToChat")}
        </button>
        <h1 className="mb-7 text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">
          {t("extensions.title")}
        </h1>
        <ExtensionsCatalog />
      </div>
    </main>
  );
}
