import { expect, spyOn, test } from "bun:test"
import * as childProcess from "node:child_process"
import { macOSFonts } from "./macos-fonts"

test("macOS font lookup preserves system-resolved paths and regular/bold face identity", () => {
  const regular = { path: "/System/Library/Fonts/STHeiti Light.ttc", postscriptName: "STHeitiSC-Light" }
  const bold = { path: "/System/Library/Fonts/STHeiti Medium.ttc", postscriptName: "STHeitiSC-Medium" }
  const lookup = spyOn(childProcess, "execFileSync").mockReturnValue(JSON.stringify([regular, bold]))
  try {
    expect(macOSFonts()).toEqual({ regular, bold, mono: regular })
  } finally { lookup.mockRestore() }
})

test("an unavailable macOS font URL is a font error, not an undefined file read", () => {
  const lookup = spyOn(childProcess, "execFileSync").mockReturnValue(JSON.stringify([
    { postscriptName: "STHeitiSC-Light" }, { postscriptName: "STHeitiSC-Medium" },
  ]))
  try {
    expect(macOSFonts).toThrow("check Heiti SC in macOS Font Book")
  } finally { lookup.mockRestore() }
})

test("a failed system lookup stays a recoverable diagram error", () => {
  const lookup = spyOn(childProcess, "execFileSync").mockImplementation(() => { throw new Error("lookup timed out") })
  try {
    expect(macOSFonts).toThrow("check Heiti SC in macOS Font Book")
  } finally { lookup.mockRestore() }
})
