import { describe, expect, it } from "vitest";

import { codeLanguageFromPath, normalizeCodeLanguage } from "@/lib/code-language";

describe("code language helpers", () => {
  it.each([
    ["src/App.tsx", "tsx"],
    ["templates/index.html", "markup"],
    ["Dockerfile", "docker"],
    ["Dockerfile.dev", "docker"],
    ["CMakeLists.txt", "cmake"],
    ["scripts/setup.sh:12:4", "bash"],
    ["config/settings.yaml?raw=1", "yaml"],
    ["unknown.customlang", "customlang"],
  ])("infers %s as %s", (path, language) => {
    expect(codeLanguageFromPath(path)).toBe(language);
  });

  it("normalizes aliases used by the file preview API", () => {
    expect(normalizeCodeLanguage("html")).toBe("markup");
    expect(normalizeCodeLanguage("dockerfile")).toBe("docker");
    expect(normalizeCodeLanguage(undefined)).toBe("text");
  });
});
