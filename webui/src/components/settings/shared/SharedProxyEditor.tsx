import { useState, type ComponentProps, type Ref } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { changeProxyAddress, changeProxyAuthentication, isProxyUrlReference, splitProxyUrl } from "@/lib/proxy-url";
import { cn } from "@/lib/utils";

type AddressProps = Pick<ComponentProps<typeof Input>, "id" | "aria-describedby" | "aria-invalid">;

export function SharedProxyEditor({ value, onChange, disabled, inputRef, addressProps, stackCredentials = false }: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  addressProps?: AddressProps;
  stackCredentials?: boolean;
}) {
  const { t } = useTranslation();
  const parts = splitProxyUrl(value);
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const open = expanded ?? parts.userinfo !== null;
  const reference = isProxyUrlReference(parts.address);
  const credentialsDisabled = disabled || !parts.address.trim() || reference;
  return (
    <div data-shared-proxy-editor className="w-full space-y-3">
      <Input {...addressProps} ref={inputRef} aria-label={t("settings.runtimeConfig.fields.network_proxy.label")}
        type="text" value={parts.address} disabled={disabled} autoComplete="off" spellCheck={false}
        placeholder="http://127.0.0.1:7890" className="h-10 rounded-control text-[13px]"
        onChange={(event) => onChange(changeProxyAddress(value, event.target.value))} />
      <button type="button" aria-expanded={open} onClick={() => setExpanded(!open)}
        className="flex w-full items-center justify-between gap-3 rounded-sm py-1 text-[13px] font-medium leading-5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t("settings.network.authentication")}
        <ChevronDown aria-hidden className={cn("h-3.5 w-3.5 shrink-0 transition-transform motion-reduce:transition-none", open && "rotate-180")} />
      </button>
      {open ? reference ? (
        <p className="px-1 text-[12px] leading-5 text-muted-foreground">{t("settings.network.proxyReferenceAuth")}</p>
      ) : (
        <div className={cn("grid gap-4", !stackCredentials && "sm:grid-cols-2")}>
          <label className="block space-y-1">
            <span className="px-1 text-[13px] leading-5 text-muted-foreground">{t("settings.network.username")}</span>
            <Input type="text" value={parts.username} disabled={credentialsDisabled} autoComplete="off" spellCheck={false}
              className="h-10 rounded-control text-[13px]"
              onChange={(event) => { setExpanded(true); onChange(changeProxyAuthentication(value, event.target.value, parts.password)); }} />
          </label>
          <label className="block space-y-1">
            <span className="px-1 text-[13px] leading-5 text-muted-foreground">{t("settings.network.password")}</span>
            <Input type="password" value={parts.password} disabled={credentialsDisabled} autoComplete="new-password"
              className="h-10 rounded-control text-[13px]"
              onChange={(event) => { setExpanded(true); onChange(changeProxyAuthentication(value, parts.username, event.target.value)); }} />
          </label>
        </div>
      ) : null}
    </div>
  );
}
