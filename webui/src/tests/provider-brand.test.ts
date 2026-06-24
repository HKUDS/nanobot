import { describe, expect, it } from "vitest";

import { faviconUrls, logoFallbackUrls, providerBrand } from "@/lib/provider-brand";

describe("provider brand logos", () => {
  it("uses multiple favicon sources before falling back to initials", () => {
    expect(faviconUrls("z.ai")).toEqual([
      "https://z.ai/favicon.ico",
      "https://icons.duckduckgo.com/ip3/z.ai.ico",
      "https://www.google.com/s2/favicons?domain=z.ai&sz=64",
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

  it("keeps Zhipu on the current Z.ai brand domain", () => {
    expect(providerBrand("zhipu")?.logoUrls[0]).toBe("https://z-cdn.chatglm.cn/z-ai/static/logo.svg");
    expect(providerBrand("zhipu")?.logoUrls).toContain("https://www.google.com/s2/favicons?domain=z.ai&sz=64");
    expect(providerBrand("zhipu")?.logoUrls).toContain("https://z.ai/favicon.ico");
    expect(providerBrand("zhipu")?.initials).toBe("Z");
  });

  it("uses official first-party assets for LongCat, Step Fun, and Xiaomi MIMO", () => {
    expect(providerBrand("longcat")?.logoUrls[0]).toBe("https://www.longcatai.org/favicon.svg");
    expect(providerBrand("stepfun")?.logoUrls[0]).toBe("https://www.stepfun.com/step_favicon.svg");
    expect(providerBrand("xiaomi_mimo")?.logoUrls[0]).toBe("https://mimo.xiaomi.com/mimo-v2-pro/assets/logo.svg");
    expect(providerBrand("mimo")?.logoUrls[0]).toBe("https://mimo.xiaomi.com/mimo-v2-pro/assets/logo.svg");
    expect(providerBrand("xiaomi")?.logoUrls[0]).toBe("https://mimo.xiaomi.com/mimo-v2-pro/assets/logo.svg");
  });

  it("keeps OpenRouter voice settings on the first-party brand domain", () => {
    expect(providerBrand("openrouter")?.logoUrls).toContain("https://openrouter.ai/favicon.ico");
    expect(providerBrand("openrouter")?.initials).toBe("OR");
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
