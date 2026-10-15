import type { ReactNode } from "react";
import { BookOpen, ExternalLink, Github, MessageCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsGroup } from "@/components/settings/shared/SettingsControls";

export function AboutSettingsView({ reportIssueUrl, versionCheck, starLink }: {
  reportIssueUrl: string;
  versionCheck: ReactNode;
  starLink: ReactNode;
}) {
  const { t } = useTranslation();
  const links = [
    { key: "sourceCode", icon: Github, href: "https://github.com/HKUDS/nanobot" },
    { key: "documentation", icon: BookOpen, href: "https://nanobot.wiki/" },
    { key: "reportIssue", icon: MessageCircle, href: reportIssueUrl },
  ];
  return (
    <div className="flex flex-1 flex-col gap-5">
      <div className="flex flex-col items-center gap-4 py-6 text-center">
        <img src="/brand/nanobot_mark.svg" alt="" className="h-16 w-16 select-none" draggable={false} />
        <h1><img src="/brand/nanobot_wordmark.svg" alt="nanobot" className="h-auto w-40 select-none dark:brightness-150" draggable={false} /></h1>
        {versionCheck}
      </div>
      <SettingsGroup>
        {links.map(({ key, icon: Icon, href }) => (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer"
            className="settings-list-row flex select-none items-center gap-3 text-[14px] settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
            <span className="flex-1">{t(`settings.about.${key}`)}</span>
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          </a>
        ))}
      </SettingsGroup>
      <div className="mt-auto pt-8 text-center">
        {starLink}
      </div>
    </div>
  );
}
