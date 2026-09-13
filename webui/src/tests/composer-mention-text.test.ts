import { describe, expect, it } from "vitest";

import { splitCapabilityMentionSegments } from "@/components/CliAppMentionText";
import { composerCompositionSegments, composerMentionLabel, composerMentionText, editComposerMentionText, mentionTextOffset } from "@/lib/composer-mention-text";
import type { CliAppInfo } from "@/lib/types";

const apps = [
  ["linear", "Linear"], ["drawio", "Draw.io"], ["drive", "Google Drive"],
  ["iterm2", "iTerm2"], ["gimp", "GIMP"], ["custom", "本地应用"],
  ["blank", "  "], ["first", "Same Name"], ["second", "Same Name"],
].map(([name, display_name]) => ({ name, display_name, installed: true }) as CliAppInfo);
const project = (raw: string) => composerMentionText(splitCapabilityMentionSegments(raw, apps));

describe("composer mention display text", () => {
  it.each([
    ["n @Linear @Google Drive", 0, 0, ["linear", "drive"]],
    ["@Linear n @Google Drive", 8, 8, ["linear", "drive"]],
    ["@Linear @Google Drive n", 21, 21, ["linear", "drive"]],
    ["@Lin中ear @Google Drive", 4, 4, ["drive"]],
    ["中 @Google Drive", 0, 7, ["drive"]],
  ])("keeps untouched mention identities during IME input: %s", (display, start, end, names) => {
    const original = splitCapabilityMentionSegments("@linear @drive", apps);
    const segments = composerCompositionSegments(original, display, { start, end });
    expect(segments.map(composerMentionLabel).join("")).toBe(display);
    expect(segments.flatMap(segment => segment.kind === "cli" ? [segment.app.name] : [])).toEqual(names);
  });

  it("keeps duplicate display names tied to their own identities during composition", () => {
    const original = splitCapabilityMentionSegments("@first @second", apps);
    const segments = composerCompositionSegments(original, "中 @Same Name", { start: 0, end: 10 });
    expect(segments.map(composerMentionLabel).join("")).toBe("中 @Same Name");
    expect(segments.flatMap(segment => segment.kind === "cli" ? [segment.app.name] : [])).toEqual(["second"]);
    expect(composerCompositionSegments(original, "@Same Name @Same Name")).toBe(original);
  });

  it("adds a non-breaking logo gap only to display text and maps editing around it", () => {
    const app = { ...apps[0], logo_url: "https://example.invalid/linear.svg" };
    const text = composerMentionText(splitCapabilityMentionSegments("@linear next", [app]));
    expect(text.display).toBe("@\u00a0Linear next");
    expect(text.raw).toBe("@linear next");
    expect(mentionTextOffset(text, 8, "toRaw")).toBe(7);
    expect(mentionTextOffset(text, 7, "toDisplay")).toBe(8);
    expect(editComposerMentionText(text, "@\u00a0Linear! next", 9, { start: 8, end: 8 }))
      .toEqual({ value: "@linear! next", cursor: 8 });
  });

  it("preserves brand spelling without changing the raw identifiers", () => {
    const raw = "@linear @drawio @drive @iterm2 @gimp @custom @blank @unknown";
    const text = project(raw);
    expect(text.raw).toBe(raw);
    expect(text.display).toBe("@Linear @Draw.io @Google Drive @iTerm2 @GIMP @本地应用 @blank @unknown");
  });

  it("maps both ends of every mention and all surrounding text positions", () => {
    const text = project("请用 @drive 和 @drawio 处理\n文件");
    for (let raw = 0; raw <= text.raw.length; raw++) {
      if (text.mentions.some((mention) => raw > mention.start && raw < mention.end)) continue;
      expect(mentionTextOffset(text, mentionTextOffset(text, raw, "toDisplay"), "toRaw")).toBe(raw);
    }
  });

  it.each([
    ["@drive", "@Google Drive hello", 19, "@drive hello"],
    ["@drive done", "@Google Drive !done", 15, "@drive !done"],
    ["@drive @drawio", "@Google Drive  @Draw.io", 14, "@drive  @drawio"],
    ["@drive done", "@Google Driv done", 12, " done"],
    ["@drive done", "@oogle Drive done", 1, " done"],
    ["@drive done", "@Google XDrive done", 9, "X done"],
    ["@drive @drawio", "@Google Drive\n@Draw.io", 14, "@drive\n@drawio"],
    ["@first @second", "@Same Name @Same Name!", 21, "@first @second!"],
  ])("applies %s → %s without rewriting untouched mentions", (raw, display, caret, expected) => {
    expect(editComposerMentionText(project(raw), display, caret as number).value).toBe(expected);
  });

  it("replaces a selected mention without losing a shared @ prefix", () => {
    expect(editComposerMentionText(project("@drive"), "@linear", 7, { start: 0, end: 13 }))
      .toEqual({ value: "@linear", cursor: 7 });
  });
});
