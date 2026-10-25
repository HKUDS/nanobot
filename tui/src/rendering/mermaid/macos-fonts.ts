import { execFileSync } from "node:child_process"
import { homedir } from "node:os"
import { isAbsolute } from "node:path"
import type { DiagramFont, DiagramInput } from "./types"

// Ask CoreText for installed font URLs: recent macOS versions manage PingFang
// under versioned Assets directories. No app automation or development toolchain is used.
const query = `
ObjC.import("CoreText");
JSON.stringify(["PingFangSC-Regular", "PingFangSC-Semibold"].map(function(name) {
  const font = $.CTFontCreateWithName($(name), 12, null);
  const actual = ObjC.unwrap(ObjC.castRefToObject($.CTFontCopyPostScriptName(font)));
  if (actual !== name) throw new Error("PingFang font unavailable");
  const url = $.CTFontCopyAttribute(font, $.kCTFontURLAttribute);
  return { path: ObjC.unwrap(url.path), postscriptName: actual };
}));
`

function isFont(value: unknown): value is DiagramFont {
  return value !== null && typeof value === "object"
    && "path" in value && typeof value.path === "string" && isAbsolute(value.path)
    && "postscriptName" in value && typeof value.postscriptName === "string" && value.postscriptName.length > 0
}

/** Called only in the diagram worker; getFonts caches the resolved faces. */
export function macOSFonts(): NonNullable<DiagramInput["fonts"]> {
  try {
    const fonts: unknown = JSON.parse(execFileSync("/usr/bin/osascript", ["-l", "JavaScript", "-e", query], {
      encoding: "utf8", timeout: 5000, maxBuffer: 4096, stdio: ["ignore", "pipe", "pipe"],
      env: { HOME: homedir(), PATH: "/usr/bin:/bin" },
    }))
    if (!Array.isArray(fonts) || fonts.length !== 2 || !fonts.every(isFont)) throw new Error("Invalid font lookup result")
    const regular = fonts[0]!, bold = fonts[1]!
    return { regular, bold, mono: regular }
  } catch (cause) {
    throw new Error("Diagram font unavailable (check PingFang in macOS Font Book)", { cause })
  }
}
