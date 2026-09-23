import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginHelpProps } from "@/channel-plugins/types";
import { DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

export function LinearHelpContent({ feature }: ChannelPluginHelpProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const allowFrom = feature.config_values?.["channels.linear.allowFrom"]?.trim() ?? "";

  return (
    <>
      <p className="max-w-72 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
        {allowFrom === "*"
          ? tx("custom.accessAll", "Every member of an authorized workspace can run this agent.")
          : allowFrom
            ? tx("custom.accessRestricted", "Only the Linear user IDs listed in Advanced can run this agent.")
            : tx("custom.accessPairing", "Pair on first use; connect Linear MCP to search or edit issues.")}
      </p>
      <DropdownMenuSeparator />
    </>
  );
}
