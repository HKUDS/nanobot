import { useEffect, useId, useMemo, useRef } from "react";
import { Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ProviderIcon } from "@/components/settings/shared/ProviderIcon";
import { TruncatedTextTooltip } from "@/components/ui/tooltip";
import { SearchInput } from "@/components/ui/input";
import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { SettingsPayload } from "@/lib/types";

const PROVIDER_GROUPS = [
  { id: "oauth", labelKey: "settings.providers.providerGroupOAuth", label: "OAuth" },
  { id: "api_key", labelKey: "settings.providers.providerGroupApiKey", label: "API Key" },
  { id: "local", labelKey: "settings.providers.providerGroupLocal", label: "Local" },
] as const;


const PROVIDER_SEARCH_ALIASES: Record<string, string> = {
  anthropic: "claude 克劳德 克勞德",
  deepseek: "深度求索 深度探索",
  zhipu: "智谱 智譜 glm z.ai",
  dashscope: "阿里 通义 通義 千问 千問 qwen",
  moonshot: "月之暗面 kimi",
  kimi_coding: "月之暗面 kimi coding",
  volcengine: "火山引擎 豆包 doubao",
  volcengine_coding_plan: "火山引擎 豆包 doubao",
  minimax: "海螺 稀宇",
  minimax_anthropic: "海螺 稀宇",
  siliconflow: "硅基流动 矽基流動 硅基流動",
  stepfun: "阶跃星辰 階躍星辰",
  xiaomi_mimo: "小米 mimo",
  longcat: "美团 美團",
  qianfan: "百度 千帆 文心",
  ant_ling: "蚂蚁 螞蟻 百灵 百靈",
};

export function ProviderSearchList({ providers, showBrandLogos, query, onQueryChange, onSelect, onCustom, onClose }: {
  providers: SettingsPayload["providers"];
  showBrandLogos: boolean;
  query: string;
  onQueryChange: (query: string) => void;
  onSelect: (name: string) => void;
  onCustom: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const mobile = useMediaQuery("(max-width: 639px)");
  const inputRef = useRef<HTMLInputElement>(null);
  const groupId = useId();
  useEffect(() => {
    if (!mobile) inputRef.current?.focus({ preventScroll: true });
  }, [mobile]);
  const filtered = useMemo(() => {
    const normalize = (value: string) => value.toLocaleLowerCase().replace(/[\s_.-]+/g, "");
    const normalizedQuery = normalize(query);
    return providers.filter((provider) => normalize(
      `${provider.name} ${provider.label} ${PROVIDER_SEARCH_ALIASES[provider.name] ?? ""}`,
    ).includes(normalizedQuery));
  }, [providers, query]);
  const groups = useMemo(() => PROVIDER_GROUPS.map((group) => ({
    ...group,
    providers: filtered.filter((provider) => providerGroup(provider) === group.id),
  })).filter((group) => group.providers.length > 0), [filtered]);
  const values = useMemo(
    () => groups.flatMap((group) => group.providers.map((provider) => provider.name)),
    [groups],
  );
  const { inputProps, listProps, getOptionProps } = useComboboxNavigation({
    open: true, values, onSelect, onClose,
  });
  const searchLabel = t("settings.providers.searchPlaceholder", { defaultValue: "Search providers" });
  return <>
    <div className="mb-3 shrink-0 overflow-y-auto px-5 scrollbar-thin scrollbar-track-transparent">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <SearchInput {...inputProps} ref={inputRef} value={query} onChange={(event) => onQueryChange(event.target.value)}
          aria-label={searchLabel} placeholder={searchLabel}
          className="rounded-xl border-transparent bg-muted/60 pl-9" />
      </div>
    </div>
    <div {...listProps} aria-label={searchLabel}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-3 scrollbar-thin scrollbar-track-transparent">
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.id} role="group" aria-labelledby={`${groupId}-${group.id}`}>
            <div id={`${groupId}-${group.id}`} className="px-2 pb-1 text-[11px] font-medium text-muted-foreground sm:px-3">
              {t(group.labelKey, { defaultValue: group.label })}
            </div>
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
              {group.providers.map((provider) => <ComboboxOption key={provider.name} {...getOptionProps(provider.name)}
                aria-label={provider.label}
                className="min-h-11 min-w-0 gap-2 rounded-xl px-2 py-2 text-[13px] font-normal sm:gap-3 sm:px-3 sm:text-sm">
                <ProviderIcon provider={provider.name} showBrandLogos={showBrandLogos} compact />
                <TruncatedTextTooltip text={provider.label} className="flex-1" />
              </ComboboxOption>)}
            </div>
          </div>
        ))}
      </div>
      {filtered.length === 0 ? <p role="status" className="px-3 py-12 text-center text-sm text-muted-foreground">
        {t("settings.providers.noMatches", { defaultValue: "No matching providers." })}
      </p> : null}
    </div>
    <div className="shrink-0 overflow-y-auto border-t border-border/50 px-5 py-3 scrollbar-thin scrollbar-track-transparent">
      <button type="button" onClick={onCustom}
        className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Plus className="h-6 w-6 shrink-0 p-0.5 text-muted-foreground" aria-hidden />
        <span className="flex-1">{t("settings.providers.customProvider", { defaultValue: "Custom provider" })}</span>
      </button>
    </div>
  </>;
}

function providerGroup(provider: SettingsPayload["providers"][number]): typeof PROVIDER_GROUPS[number]["id"] {
  if (provider.auth_type === "oauth") return "oauth";
  return provider.model_catalog === "local" ? "local" : "api_key";
}


