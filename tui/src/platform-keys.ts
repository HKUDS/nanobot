export function optionArrowUp(platform: string = process.platform): string {
  return platform === "darwin" ? "⌥↑" : "alt+↑"
}
