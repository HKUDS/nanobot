/**
 * Providers report the same model under different ids: the Codex backend
 * answers with `openai-codex/gpt-6.1-sol` while other calls record the bare
 * `gpt-6-astra`. Grouping stays per provider, but the model name has to be
 * normalized first, otherwise one model shows up as several cards.
 */
const SEPARATORS = /[^a-z0-9]/g;

function identity(value: string): string {
  return value.toLowerCase().replace(SEPARATORS, "");
}

export function normalizeUsageModel(provider: string, model: string): string {
  const separator = model.indexOf("/");
  if (separator <= 0) return model;
  const prefix = identity(model.slice(0, separator));
  const owner = identity(provider);
  // Only strip a prefix that names the provider itself; `qwen/…` under a
  // custom provider is part of the model name.
  return prefix && owner.startsWith(prefix) ? model.slice(separator + 1) : model;
}
