import { CircleHelp, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
import { docsUrlWithBase } from "@/components/settings/channels/catalog";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import type { NanobotFeatureInfo } from "@/lib/types";

export function ChannelHelpMenu({ feature, chatAppsDocsUrl }: {
  feature: NanobotFeatureInfo;
  chatAppsDocsUrl?: string;
}) {
  const { t, i18n } = useTranslation();
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const links = [
    { url: setup.officialUrl, label: setup.officialLabel },
    { url: docsUrlWithBase(setup.docsUrl, chatAppsDocsUrl), label: setup.docsLabel },
  ].filter((link) => link.url);
  if (!links.length) return null;
  const label = t("settings.channels.help", { defaultValue: "Help" });
  return (
    <TooltipProvider>
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button type="button" aria-label={label}
              className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              <CircleHelp className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end">
        {links.map((link) => (
          <DropdownMenuItem key={link.url} asChild>
            <a href={link.url} target="_blank" rel="noreferrer">
              {link.label ?? label}
              <ExternalLink className="ml-2 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
    </TooltipProvider>
  );
}
