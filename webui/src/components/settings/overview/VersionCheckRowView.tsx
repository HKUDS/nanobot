import { ArrowUpCircle, Check, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

export type VersionInfoProps = { currentVersion?: string; currentCommit?: string | null };
export type VersionCheckState =
  | { type: "up-to-date" }
  | { type: "update"; latestVersion: string; pypiUrl?: string }
  | { type: "error"; message: string }
  | null;

export function VersionCheckRowView({ currentVersion, currentCommit, checking, result, onCheck }: VersionInfoProps & {
  checking: boolean;
  result: VersionCheckState;
  onCheck: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="min-w-0">
        <div className="sr-only">
          {tx("settings.about.version", "Version")}
        </div>
        <div className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
          {currentVersion ? `v${currentVersion}` : "nanobot"}
          {currentCommit && (
            <>
              <span aria-hidden> (</span>
              <a href={`https://github.com/HKUDS/nanobot/commit/${currentCommit}`}
                target="_blank" rel="noopener noreferrer" title={currentCommit}
                className="font-mono hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {currentCommit.slice(0, 7)}
              </a>
              <span aria-hidden>)</span>
            </>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={onCheck}
          disabled={checking}
          className="rounded-full"
        >
          {checking ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <ArrowUpCircle className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {checking
            ? tx("settings.about.checking", "Checking...")
            : tx("settings.about.checkForUpdates", "Check for updates")}
        </Button>
        {result?.type === "up-to-date" ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-300">
            <Check className="h-3 w-3" aria-hidden />
            {tx("settings.about.upToDate", "You're up to date")}
          </span>
        ) : null}
        {result?.type === "update" ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-blue-600 dark:text-blue-300">
            <ArrowUpCircle className="h-3 w-3" aria-hidden />
            {t("settings.about.updateAvailable", {
              defaultValue: "Update available v{{version}}",
              version: result.latestVersion,
            })}
            {result.pypiUrl ? (
              <a
                href={result.pypiUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
              >
                PyPI
                <ExternalLink className="h-2.5 w-2.5" aria-hidden />
              </a>
            ) : null}
          </span>
        ) : null}
        {result?.type === "error" ? (
          <span className="text-[12px] text-destructive">{result.message}</span>
        ) : null}
      </div>
    </div>
  );
}
