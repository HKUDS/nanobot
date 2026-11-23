/** Only a successful switch changes the badge; never infer a preset from displayed text. */
export function switchedModelPreset(result: unknown): string | undefined {
  if (!result || typeof result !== "object" || !("command" in result) || result.command !== "/model"
    || !("parts" in result) || !Array.isArray(result.parts)) return undefined
  for (const part of result.parts as unknown[]) {
    if (part && typeof part === "object" && "key" in part && part.key === "model.switched"
      && "values" in part && part.values && typeof part.values === "object" && "preset" in part.values
      && typeof part.values.preset === "string" && part.values.preset) return part.values.preset
  }
  return undefined
}
