import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

export function LinearHelpContent() {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");

  return (
    <>
      <p className="max-w-72 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
        {tx("members.guide", "Use Member access to approve teammates without pairing codes. Existing approvals still work unless switched off. Connect Linear MCP to search or edit issues.")}
      </p>
      <DropdownMenuSeparator />
    </>
  );
}
