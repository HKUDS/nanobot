import { describe, expect, it } from "vitest";

import {
  browserSafeFaviconUrls,
  faviconUrls,
  isGenericRepositoryLogoUrl,
  logoFallbackUrls,
  providerBrand,
} from "@/lib/provider-brand";

describe("provider brand logos", () => {
  it("covers Eden AI, OpenCode variants, and Kimi Coding with their official assets", () => {
    expect(providerBrand("edenai")?.logoUrl).toContain("cdn.prod.website-files.com/");
    expect(providerBrand("opencode")?.logoUrl).toBe("https://opencode.ai/favicon-96x96-v3.png");
    expect(providerBrand("opencode_zen")).toBe(providerBrand("opencode"));
    expect(providerBrand("opencode_go")).toBe(providerBrand("opencode"));
    expect(providerBrand("kimi_coding")?.logoUrl).toBe(
      "https://raw.githubusercontent.com/MoonshotAI/Branding-Guide/main/scenarios/04-k-only/k-only-light.svg",
    );
    expect(providerBrand("kimi_coding")).not.toBe(providerBrand("moonshot"));
  });

  it("uses multiple favicon sources before falling back to initials", () => {
    expect(faviconUrls("z.ai")).toEqual([
      "https://z.ai/favicon.ico",
      "https://icons.duckduckgo.com/ip3/z.ai.ico",
      "https://www.google.com/s2/favicons?domain=z.ai&sz=64",
    ]);
  });

  it("uses cross-origin-safe favicon sources first for arbitrary web pages", () => {
    expect(browserSafeFaviconUrls("openai.com")).toEqual([
      "https://favicon.im/openai.com?larger=true",
      "https://www.google.com/s2/favicons?domain=openai.com&sz=64",
      "https://icons.duckduckgo.com/ip3/openai.com.ico",
      "https://openai.com/favicon.ico",
    ]);
  });

  it("keeps explicit Google favicon URLs first before trying fallbacks", () => {
    expect(logoFallbackUrls("https://www.google.com/s2/favicons?domain=browserbase.com&sz=64")).toEqual([
      "https://www.google.com/s2/favicons?domain=browserbase.com&sz=64",
      "https://browserbase.com/favicon.ico",
      "https://icons.duckduckgo.com/ip3/browserbase.com.ico",
    ]);
  });

  it("normalizes path-like favicon domains for secondary fallbacks", () => {
    expect(logoFallbackUrls("https://www.google.com/s2/favicons?domain=github.com/HKUDS/CLI-Anything&sz=64")).toEqual([
      "https://www.google.com/s2/favicons?domain=github.com/HKUDS/CLI-Anything&sz=64",
      "https://github.com/favicon.ico",
      "https://icons.duckduckgo.com/ip3/github.com.ico",
      "https://www.google.com/s2/favicons?domain=github.com%2FHKUDS%2FCLI-Anything&sz=64",
    ]);
  });

  it("distinguishes repository host favicons from product identities", () => {
    expect(
      isGenericRepositoryLogoUrl(
        "https://www.google.com/s2/favicons?domain=github.com/HKUDS/CLI-Anything&sz=64",
      ),
    ).toBe(true);
    expect(isGenericRepositoryLogoUrl("https://github.com/favicon.ico")).toBe(true);
    expect(isGenericRepositoryLogoUrl("https://raw.githubusercontent.com/org/repo/logo.svg")).toBe(false);
    expect(isGenericRepositoryLogoUrl("https://blender.org/favicon.ico")).toBe(false);
  });

  it("keeps Zhipu on the current Z.ai brand domain", () => {
    expect(providerBrand("zhipu")?.logoUrls[0]).toBe("https://mintcdn.com/zhipu-32152247/B_E8wI-eiNa1QlPV/logo/dark.svg");
    expect(providerBrand("zhipu")?.logoUrls).toContain("https://z-cdn.chatglm.cn/z-ai/static/logo.svg");
    expect(providerBrand("zhipu")?.logoUrls).toContain("https://www.google.com/s2/favicons?domain=z.ai&sz=64");
    expect(providerBrand("zhipu")?.logoUrls).toContain("https://z.ai/favicon.ico");
    expect(providerBrand("zhipu")?.initials).toBe("Z");
  });

  it("uses LongCat's official cat logo and official domain for every fallback", () => {
    const logoUrl = "https://s3plus.meituan.net/aigc-media-resources/longcat/yeqian-logo.svg";
    expect(providerBrand("longcat")?.logoUrl).toBe(logoUrl);
    expect(providerBrand("longcat")?.logoUrls).toEqual([
      logoUrl,
      ...browserSafeFaviconUrls("longcat.ai"),
    ]);
  });

  it("uses official first-party assets for Step Fun and Xiaomi MIMO", () => {
    expect(providerBrand("stepfun")?.logoUrls[0]).toBe("https://www.stepfun.com/step_favicon.svg");
    expect(providerBrand("xiaomi_mimo")?.logoUrls[0]).toBe("https://cdn.cnbj1.fds.api.mi-img.com/aife/mimo-blog-fe/doc_build/mimo.ico");
    expect(providerBrand("mimo")).toBe(providerBrand("xiaomi_mimo"));
    expect(providerBrand("xiaomi")).toBe(providerBrand("xiaomi_mimo"));
  });

  it("uses the Copilot mark rather than the generic GitHub favicon", () => {
    expect(providerBrand("github_copilot")?.logoUrl).toBe("https://raw.githubusercontent.com/primer/octicons/main/icons/copilot-24.svg");
  });

  it("never substitutes a favicon proxy's placeholder for SearXNG", () => {
    const brand = providerBrand("searxng")!;
    expect(brand.logoUrl).toBe(brand.logoUrls[0]);
    expect(brand.logoUrls).toEqual([
      "https://raw.githubusercontent.com/searxng/searxng/master/searx/static/themes/simple/img/favicon.svg",
      "https://raw.githubusercontent.com/searxng/searxng/master/searx/static/themes/simple/img/favicon.png",
    ]);
  });

  it("keeps OpenRouter voice settings on the first-party brand domain", () => {
    expect(providerBrand("openrouter")?.logoUrl).toBe("https://openrouter.ai/brand/logos/transparent/glyph/svg/glyph-grape.svg");
    expect(providerBrand("openrouter")?.logoUrls).toContain("https://openrouter.ai/favicon.ico");
    expect(providerBrand("openrouter")?.initials).toBe("OR");
  });

  it("maps both xAI Grok spellings to the xAI brand", () => {
    expect(providerBrand("xai_grok")?.logoUrls).toContain("https://x.ai/favicon.ico");
    expect(providerBrand("xai-grok")?.initials).toBe("xAI");
  });

  it("keeps AssemblyAI voice settings on the first-party brand domain", () => {
    expect(providerBrand("assemblyai")?.logoUrls).toContain("https://assemblyai.com/favicon.ico");
    expect(providerBrand("assemblyai")?.initials).toBe("AA");
  });

  it("keeps Bocha web search settings on the first-party brand domain", () => {
    expect(providerBrand("bocha")?.logoUrls).toContain("https://bochaai.com/favicon.ico");
    expect(providerBrand("bocha")?.initials).toBe("B");
  });

  it("keeps Keenable web search settings on the first-party brand domain", () => {
    expect(providerBrand("keenable")?.logoUrls).toContain("https://keenable.ai/favicon.ico");
    expect(providerBrand("keenable")?.initials).toBe("K");
  });
});
