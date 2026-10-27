import { describe, expect, it } from "vitest";

import { getDiffMetadata } from "@/components/thread/activity/PierreFileDiff";
import { DIFF_GAP_HEIGHT, diffRenderWindow, diffRowOffsets } from "@/components/thread/activity/diff-render-window";
import { parseRenderableFileDiff } from "@/lib/file-diff";

const patch = (name: string, content: string, start = 20) => `--- a/${name}\n+++ b/${name}\n@@ -0,0 +${start},1 @@\n+${content}\n`;

describe("file diff render metadata", () => {
  it("preserves complete source and coordinates and reuses a revision across remounts", () => {
    const text = "--- a/fixture.ts\n+++ b/fixture.ts\n@@ -4,3 +4,3 @@\n export function run() {\n-  return oldValue;\n+  return newValue;\n \n";
    const file = getDiffMetadata(text, "typescript");
    expect(file.hunks).toHaveLength(1);
    expect(file.hunks[0]).toMatchObject({ deletionStart: 4, additionStart: 4, deletionCount: 3, additionCount: 3, unifiedLineCount: 4 });
    expect(file.deletionLines).toEqual(["export function run() {\n", "  return oldValue;\n", "\n"]);
    expect(file.additionLines).toEqual(["export function run() {\n", "  return newValue;\n", "\n"]);
    expect(getDiffMetadata(text, "typescript")).toBe(file);
    expect(getDiffMetadata(text.replace("newValue", "changedValue"), "typescript").cacheKey).not.toBe(file.cacheKey);
    expect(getDiffMetadata(text, "javascript").cacheKey).not.toBe(file.cacheKey);
  });

  it.each([["markup", "html"], ["docker", "dockerfile"], ["ini", "ini"], ["lock", "text"]])("maps %s to %s without losing source", (language, expected) => {
    const file = getDiffMetadata(patch("fixture", "<span>中文 & text</span>"), language);
    expect(file.lang).toBe(expected);
    expect(file.additionLines).toEqual(["<span>中文 & text</span>\n"]);
    expect(file.hunks[0]).toMatchObject({ deletionCount: 0, additionStart: 20, additionCount: 1 });
  });

  it("evicts older revisions under the entry budget without reusing their identity", () => {
    const text = patch("old.ts", "old revision");
    const old = getDiffMetadata(text, "typescript");
    for (let i = 0; i < 16; i++) getDiffMetadata(patch(`revision-${i}.ts`, `const item = ${i};`), "typescript");
    const reloaded = getDiffMetadata(text, "typescript");
    expect(reloaded.cacheKey).not.toBe(old.cacheKey);
    expect(reloaded.additionLines).toEqual(old.additionLines);
  });
});

describe("file diff render windows", () => {
  const lines = Array.from({ length: 200 }, (_, i) => `+export const item${i} = ${i};`);
  const text = `--- a/fixture.ts\n+++ b/fixture.ts\n@@ -0,0 +1,200 @@\n${lines.join("\n")}\n@@ -500,0 +501,200 @@\n${lines.join("\n")}\n`;
  const diff = parseRenderableFileDiff({ format: "unified", text });

  it("keeps the initial 160-line disclosure bounded and reserves no space for hidden content", () => {
    const offsets = diffRowOffsets(diff, 160, 24);
    expect(offsets).toHaveLength(161);
    expect(offsets.at(-1)).toBe(160 * 24);
    expect(diffRenderWindow(diff, offsets, 0, 900, 24)).toEqual({ startingLine: 0, totalLines: 160, bufferBefore: 0, bufferAfter: 0 });
  });

  it("retains a fixed row budget while an overlapping viewport remains in the same start chunk", () => {
    const offsets = diffRowOffsets(diff, 400, 24);
    expect(diffRenderWindow(diff, offsets, -900, 1800, 24)).toEqual(diffRenderWindow(diff, offsets, -300, 2400, 24));
  });

  it("covers the requested overscan in short and tall reading viewports", () => {
    for (const lineHeight of [21.1875, 23.59375, 26]) {
      const offsets = diffRowOffsets(diff, 400, lineHeight);
      const height = offsets.at(-1)!;
      for (const viewportHeight of [240, 390, 844, 1050]) {
        for (let y = 0; y < height; y += lineHeight * 10) {
          const top = y - viewportHeight;
          const bottom = y + viewportHeight * 2;
          const window = diffRenderWindow(diff, offsets, top, bottom, lineHeight);
          expect(window.bufferBefore).toBeLessThanOrEqual(Math.max(0, top));
          expect(height - window.bufferAfter).toBeGreaterThanOrEqual(Math.min(height, bottom));
        }
      }
    }
  });

  it("preserves total geometry and gap ownership across adjacent virtual windows", () => {
    const offsets = diffRowOffsets(diff, 400, 24);
    expect(offsets.at(-1)).toBe(400 * 24 + DIFF_GAP_HEIGHT);
    const first = diffRenderWindow(diff, offsets, 0, 3840, 24);
    expect(first).toEqual({ startingLine: 0, totalLines: 200, bufferBefore: 0, bufferAfter: 200 * 24 + DIFF_GAP_HEIGHT });
    const second = diffRenderWindow(diff, offsets, 4827, 6000, 24);
    expect(second.startingLine).toBe(200);
    expect(second.bufferBefore).toBe(200 * 24);
    expect(second.totalLines * 24 + DIFF_GAP_HEIGHT + second.bufferBefore + second.bufferAfter).toBe(offsets.at(-1));
    const tail = diffRenderWindow(diff, offsets, 30000, 32000, 24);
    expect(tail.startingLine + tail.totalLines).toBe(400);
    expect(tail.bufferAfter).toBe(0);
  });
});
