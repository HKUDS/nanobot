import { describe, expect, it } from "vitest";

import { IMAGE_GAP, layoutImageRows } from "@/lib/image-gallery-layout";

const square = { width: 800, height: 800 };

describe("ordered image layout", () => {
  it("chooses two balanced rows for four square images, rather than a tiny single strip", () => {
    const rows = layoutImageRows([square, square, square, square], 360, 144, 224);
    expect(rows.map((row) => row.widths.length)).toEqual([2, 2]);
    for (const row of rows) {
      expect(row.height).toBe(176);
      expect(row.widths).toEqual([176, 176]);
    }
  });

  it.each([360, 240])("preserves the order and native proportions of mixed images at %ipx", (width) => {
    const images = [
      { width: 1200, height: 800 },
      { width: 600, height: 900 },
      square,
      { width: 1600, height: 900 },
    ];
    const rows = layoutImageRows(images, width, 144, 224);
    let position = 0;
    for (const row of rows) {
      expect(row.start).toBe(position);
      expect(row.height).toBeGreaterThan(0);
      expect(row.height).toBeLessThanOrEqual(224);
      expect(row.widths.reduce((sum, item) => sum + item, IMAGE_GAP * (row.widths.length - 1))).toBeLessThanOrEqual(width + 0.001);
      for (const tileWidth of row.widths) {
        expect(tileWidth / row.height).toBeCloseTo(images[position].width / images[position].height);
        position += 1;
      }
    }
    expect(position).toBe(images.length);
    expect(rows.length).toBeLessThanOrEqual(2);
  });

  it("fits a single portrait without stretching it into a square or exceeding the height limit", () => {
    const [row] = layoutImageRows([{ width: 600, height: 900 }], 360, 144, 320);
    expect(row.height).toBe(320);
    expect(row.widths[0]).toBeCloseTo(320 * 2 / 3);
  });

  it("does not enlarge a small image beyond its original resolution", () => {
    const [row] = layoutImageRows([{ width: 48, height: 32 }], 360, 144, 320);
    expect(row).toEqual({ start: 0, widths: [48], height: 32 });
  });

  it("gives extreme screenshots a bounded frame instead of a nearly invisible sliver", () => {
    const [long] = layoutImageRows([{ width: 600, height: 4800 }], 360, 144, 320);
    const [wide] = layoutImageRows([{ width: 4800, height: 600 }], 360, 144, 320);
    expect(long).toEqual({ start: 0, widths: [160], height: 320 });
    expect(wide).toEqual({ start: 0, widths: [360], height: 120 });
  });
});
