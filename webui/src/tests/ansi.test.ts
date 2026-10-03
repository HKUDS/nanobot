import { describe, expect, it } from "vitest";

import { parseAnsiSegments } from "@/lib/ansi";

describe("ANSI reset", () => {
  it.each(["0", ""])("clears foreground and background with SGR %s", (reset) => {
    const esc = String.fromCharCode(27);
    expect(parseAnsiSegments(`${esc}[31;44;1merror${esc}[${reset}m plain`)).toEqual([
      { text: "error", style: { color: "#cd3131", backgroundColor: "#2472c8", fontWeight: 700 } },
      { text: " plain", style: undefined },
    ]);
  });

  it("applies a new foreground after resetting the previous background", () => {
    const esc = String.fromCharCode(27);
    expect(parseAnsiSegments(`${esc}[31;44merror${esc}[0;32m success`)).toEqual([
      { text: "error", style: { color: "#cd3131", backgroundColor: "#2472c8" } },
      { text: " success", style: { color: "#0dbc79" } },
    ]);
  });
});
