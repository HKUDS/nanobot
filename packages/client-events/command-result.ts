import core from '../../nanobot/command/locales/core.json'
import palette from '../../nanobot/command/locales/palette.json'
import dream from '../../nanobot/command/locales/dream.json'
import pairing from '../../nanobot/command/locales/pairing.json'

const catalog: Record<string, Record<string, string>> = { ...core, ...palette, ...dream, ...pairing }

export function commandLocale(locale: string): string {
  const tag = locale.toLowerCase().split(/[.@]/)[0]?.replaceAll('_', '-') ?? ''
  const base = tag.split('-')[0] || 'en'
  if (base === 'zh') return /-(tw|hk|mo|hant)(-|$)/.test(tag) ? 'zh-TW' : 'zh-CN'
  return base === 'pt' ? 'pt-BR' : base
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function template(key: string, locale: string): string | undefined {
  if (!Object.hasOwn(catalog, key)) return undefined
  const entry = catalog[key]!
  const code = commandLocale(locale)
  return Object.hasOwn(entry, code) ? entry[code] : entry.en
}

export function commandLabel(command: string, field: 'title' | 'description', locale: string): string | undefined {
  return template(`palette.${command.replace(/^\//, '')}.${field}`, locale)
}

/** Unknown or malformed receipts retain their server-rendered text. Values are never interpreted as templates. */
export function renderCommandResult(result: unknown, locale: string): string | undefined {
  if (!record(result) || typeof result.command !== 'string' || !Array.isArray(result.parts)) return undefined
  const lines: string[] = []
  for (const part of result.parts as unknown[]) {
    if (!record(part)) return undefined
    if (typeof part.text === 'string') { lines.push(part.text); continue }
    if (typeof part.key !== 'string' || !record(part.values)) return undefined
    if (part.prefix !== undefined && typeof part.prefix !== 'string') return undefined
    const format = template(part.key, locale)
    if (format === undefined) return undefined
    const values = part.values
    let valid = true
    lines.push((part.prefix ?? '') + format.replace(/\{(\w+)\}/g, (_, name: string) => {
      const value = values[name]
      if (typeof value === 'string' || typeof value === 'number') return String(value)
      valid = false
      return ''
    }))
    if (!valid) return undefined
  }
  return lines.join('\n')
}
