import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";

export function OAuthClientNameField({ value, disabled, onChange }: { value: string; disabled?: boolean; onChange: (value: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="text-[12.5px]">
      <label className="mt-3 block">
        <span className="mb-1.5 block font-medium">{t("settings.mcp.oauthClientName")}</span>
        <Input value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} placeholder="nanobot" className="h-10 rounded-full" />
      </label>
      <p className="mt-2 text-muted-foreground">{t("settings.mcp.oauthClientNameHelp")}</p>
    </div>
  );
}
