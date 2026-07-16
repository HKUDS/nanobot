export interface ProviderBrand {
  logoUrl: string;
  logoUrls: string[];
  color: string;
  initials: string;
}

function officialFaviconUrl(domain: string): string {
  return `https://${domain}/favicon.ico`;
}

function duckDuckGoFaviconUrl(domain: string): string {
  return `https://icons.duckduckgo.com/ip3/${encodeURIComponent(domain)}.ico`;
}

function googleFaviconUrl(domain: string): string {
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`;
}

export function faviconUrls(domain: string): string[] {
  const faviconDomain = faviconDomainFromValue(domain);
  return [
    officialFaviconUrl(faviconDomain),
    duckDuckGoFaviconUrl(faviconDomain),
    googleFaviconUrl(domain),
  ];
}

function brand(
  domain: string,
  color: string,
  initials: string,
  logoOverrides: string[] = [],
): ProviderBrand {
  const logoUrls = [...logoOverrides];
  faviconUrls(domain).forEach((url) => addUniqueLogoUrl(logoUrls, url));
  return {
    logoUrl: logoUrls[0],
    logoUrls,
    color,
    initials,
  };
}

function addUniqueLogoUrl(urls: string[], url: string | null | undefined): void {
  const value = url?.trim();
  if (value && !urls.includes(value)) urls.push(value);
}

function domainFromLogoUrl(url: string): string | null {
  if (url.startsWith("/")) return null;
  try {
    const parsed = new URL(url);
    if (!/^https?:$/.test(parsed.protocol)) return null;
    const host = parsed.hostname.toLowerCase();
    if (host === "www.google.com" || host === "google.com") {
      return parsed.searchParams.get("domain");
    }
    if (host === "icons.duckduckgo.com") {
      const match = parsed.pathname.match(/^\/ip3\/(.+)\.ico$/);
      return match ? decodeURIComponent(match[1]) : null;
    }
    return host.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function faviconDomainFromValue(value: string): string {
  const host = value.split("/")[0]?.trim();
  return host || value;
}

export function logoFallbackUrls(logoUrl: string | null | undefined): string[] {
  const value = logoUrl?.trim();
  if (!value) return [];
  if (value.startsWith("/")) return [value];

  const urls: string[] = [];
  const domain = domainFromLogoUrl(value);
  const isFaviconProxy = /^(https?:\/\/)?(www\.google\.com|google\.com|icons\.duckduckgo\.com)\//i.test(value);
  if (domain && isFaviconProxy) {
    addUniqueLogoUrl(urls, value);
    faviconUrls(domain).forEach((url) => addUniqueLogoUrl(urls, url));
    return urls;
  }
  addUniqueLogoUrl(urls, value);
  if (domain) faviconUrls(domain).forEach((url) => addUniqueLogoUrl(urls, url));
  return urls;
}

export const PROVIDER_BRAND_ALIASES: Record<string, string> = {
  brave_search: "brave",
  byteplus_coding_plan: "byteplus",
  mimo: "xiaomi_mimo",
  minimaxAnthropic: "minimax",
  minimax_anthropic: "minimax",
  openai_codex: "openai",
  xiaomi: "xiaomi_mimo",
  volcengine_coding_plan: "volcengine",
};

export const PROVIDER_LABEL_ALIASES: Record<string, string> = {
  brave_search: "Brave Search",
  byteplus_coding_plan: "BytePlus",
  minimaxAnthropic: "MiniMax",
  minimax_anthropic: "MiniMax",
  openai_codex: "OpenAI",
  volcengine_coding_plan: "Volcengine",
};

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  aihubmix: brand("aihubmix.com", "#111827", "AH"),
  ant_ling: brand("ant-ling.com", "#7C3AED", "AL"),
  anthropic: brand("anthropic.com", "#D97757", "A"),
  assemblyai: brand("assemblyai.com", "#111827", "AA"),
  atomic_chat: brand("atomic.chat", "#111827", "AC"),
  azure_openai: brand("azure.microsoft.com", "#0078D4", "AZ"),
  bedrock: brand("aws.amazon.com", "#FF9900", "AWS"),
  bocha: brand("bochaai.com", "#2563EB", "B"),
  brave: brand("brave.com", "#FB542B", "B"),
  byteplus: brand("byteplus.com", "#325CFF", "BP"),
  dashscope: brand("dashscope.aliyun.com", "#FF6A00", "DS"),
  deepseek: brand("deepseek.com", "#4D6BFE", "DS"),
  duckduckgo: brand("duckduckgo.com", "#DE5833", "DDG"),
  exa: brand("exa.ai", "#5B5BF6", "E"),
  gemini: brand("gemini.google.com", "#4285F4", "G"),
  github_copilot: brand("github.com", "#24292F", "GH"),
  groq: brand("groq.com", "#F55036", "GQ"),
  huggingface: brand("huggingface.co", "#FF9D00", "HF"),
  jina: brand("jina.ai", "#7C3AED", "J"),
  kagi: brand("kagi.com", "#FFB319", "K"),
  keenable: brand("keenable.ai", "#0EA5E9", "K"),
  lm_studio: brand("lmstudio.ai", "#111827", "LM"),
  longcat: brand("longcatai.org", "#4F8CFF", "LC", [
    "https://www.longcatai.org/favicon.svg",
  ]),
  minimax: brand("minimax.io", "#111827", "MM"),
  mistral: brand("mistral.ai", "#FA520F", "M"),
  moonshot: brand("moonshot.ai", "#111827", "MS"),
  nimble: brand("nimbleway.com", "#0E0732", "N"),
  novita: brand("novita.ai", "#7C3AED", "N"),
  olostep: brand("olostep.com", "#111827", "O"),
  nvidia: brand("nvidia.com", "#76B900", "NV"),
  ollama: brand("ollama.com", "#111827", "O"),
  openai: brand("openai.com", "#111827", "AI"),
  openrouter: brand("openrouter.ai", "#111827", "OR"),
  ovms: brand("openvino.ai", "#0071C5", "OV"),
  qianfan: brand("cloud.baidu.com", "#2932E1", "QF"),
  searxng: brand("searxng.org", "#3050FF", "SX"),
  siliconflow: brand("siliconflow.cn", "#111827", "SF"),
  skywork: brand("skywork.ai", "#5B5BF6", "SW"),
  stepfun: brand("stepfun.com", "#2F6BFF", "SF", [
    "https://www.stepfun.com/step_favicon.svg",
  ]),
  tavily: brand("tavily.com", "#111827", "T"),
  volcengine: brand("volcengine.com", "#1664FF", "VE"),
  vllm: brand("vllm.ai", "#2563EB", "VL"),
  xiaomi_mimo: brand("mimo.xiaomi.com", "#FF6900", "MI", [
    "https://mimo.xiaomi.com/mimo-v2-pro/assets/logo.svg",
  ]),
  zhipu: brand("z.ai", "#155EEF", "Z", [
    "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
    "https://www.google.com/s2/favicons?domain=z.ai&sz=64",
  ]),
};

export function providerBrand(provider: string | null | undefined): ProviderBrand | null {
  if (!provider) return null;
  const key = PROVIDER_BRAND_ALIASES[provider] ?? provider;
  return PROVIDER_BRANDS[key] ?? null;
}

export function providerDisplayLabel(
  providers: Array<{ name: string; label: string }>,
  value: string | null | undefined,
): string {
  if (!value) return "";
  return providers.find((provider) => provider.name === value)?.label
    ?? PROVIDER_LABEL_ALIASES[value]
    ?? value;
}

export function inferProviderFromModelName(modelName: string | null | undefined): string | null {
  const normalized = (modelName ?? "").trim().toLowerCase();
  if (!normalized) return null;
  const prefix = normalized.split(/[/:]/)[0];
  if (providerBrand(prefix)) return prefix;
  if (/claude|anthropic/.test(normalized)) return "anthropic";
  if (/gpt-|^o\d|chatgpt|openai/.test(normalized)) return "openai";
  if (/deepseek/.test(normalized)) return "deepseek";
  if (/gemini/.test(normalized)) return "gemini";
  if (/qwen|dashscope/.test(normalized)) return "dashscope";
  if (/kimi|moonshot/.test(normalized)) return "moonshot";
  if (/minimax/.test(normalized)) return "minimax";
  if (/mistral|mixtral/.test(normalized)) return "mistral";
  if (/skywork|skyclaw/.test(normalized)) return "skywork";
  if (/ring-/.test(normalized)) return "ant_ling";
  return null;
}
