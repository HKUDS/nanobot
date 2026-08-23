import type {
  ConfigEditorSection,
  ConfigEditorSnapshot,
} from "./protocol"

export type ConfigFieldType = "boolean" | "number" | "string" | "json"

export interface ConfigField {
  path: string
  label: string
  breadcrumb: string
  description: string
  sectionId: string
  type: ConfigFieldType
  value: unknown
  enumValues: unknown[]
  nullable: boolean
  secret: boolean
  configured: boolean
  deprecated: boolean
  advanced: boolean
  raw: boolean
}

type JsonObject = Record<string, unknown>

const BASIC_FIELD_NAMES = new Set([
  "apiBase",
  "apiKey",
  "botIcon",
  "botName",
  "enable",
  "enabled",
  "host",
  "language",
  "model",
  "port",
  "provider",
  "workspace",
])
const SHARED_CHANNEL_FIELDS = new Set([
  "extractDocumentText",
  "sendMaxRetries",
  "sendProgress",
  "sendToolHints",
  "showReasoning",
  "transcriptionLanguage",
  "transcriptionProvider",
])

function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

export function escapePointer(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1")
}

export function pointerParts(path: string): string[] {
  if (!path || path === "/") return []
  return path.replace(/^\//u, "").split("/").map(
    (part) => part.replaceAll("~1", "/").replaceAll("~0", "~"),
  )
}

function humanize(value: string): string {
  const spaced = value
    .replace(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .replace(/[_-]+/gu, " ")
    .trim()
  if (!spaced) return "Setting"
  const words = spaced.split(/\s+/u)
  return words.map((word, index) => {
    const upper = word.toLocaleUpperCase()
    if (["API", "HTTP", "HTTPS", "MCP", "URL", "ID"].includes(upper)) return upper
    return index === 0
      ? `${word.slice(0, 1).toLocaleUpperCase()}${word.slice(1)}`
      : word.toLocaleLowerCase()
  }).join(" ")
}

function refSchema(schema: JsonObject, root: JsonObject): JsonObject {
  let current = schema
  const seen = new Set<string>()
  while (typeof current.$ref === "string" && !seen.has(current.$ref)) {
    seen.add(current.$ref)
    const parts = current.$ref.replace(/^#\//u, "").split("/")
    let value: unknown = root
    for (const part of parts) {
      if (!isObject(value)) return current
      value = value[part]
    }
    if (!isObject(value)) return current
    current = value
  }
  return current
}

function schemaChoices(schema: JsonObject, root: JsonObject): JsonObject[] {
  const resolved = refSchema(schema, root)
  const choices = Array.isArray(resolved.anyOf) ? resolved.anyOf : [resolved]
  return choices.filter(isObject).map((choice) => refSchema(choice, root))
}

function valueSchema(schema: JsonObject, root: JsonObject): JsonObject {
  const choices = schemaChoices(schema, root)
  return choices.find((choice) => choice.type !== "null") || choices[0] || schema
}

function nullableSchema(schema: JsonObject, root: JsonObject): boolean {
  return schemaChoices(schema, root).some((choice) => choice.type === "null")
}

function fieldType(schema: JsonObject, value: unknown, root: JsonObject): ConfigFieldType {
  const resolved = valueSchema(schema, root)
  if (resolved.type === "boolean" || typeof value === "boolean") return "boolean"
  if (["integer", "number"].includes(String(resolved.type)) || typeof value === "number") {
    return "number"
  }
  if (resolved.type === "array" || resolved.type === "object" || isObject(value)
    || Array.isArray(value)) return "json"
  return "string"
}

function matchesPrefix(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`)
}

function sectionFor(path: string, sections: ConfigEditorSection[]): ConfigEditorSection | undefined {
  return sections.find((section) => section.prefixes.some((prefix) => matchesPrefix(path, prefix)))
}

function providerPrimaryPaths(snapshot: ConfigEditorSnapshot): string[] {
  const agents = isObject(snapshot.config.agents) ? snapshot.config.agents : {}
  const defaults = isObject(agents.defaults) ? agents.defaults : {}
  const providers = isObject(snapshot.config.providers) ? snapshot.config.providers : {}
  const configured = typeof defaults.provider === "string" ? defaults.provider : ""
  const modelProvider = typeof defaults.model === "string" ? defaults.model.split("/", 1)[0] || "" : ""
  const preferred = configured && configured !== "auto" ? configured : modelProvider
  const normalized = preferred.replace(/[^a-z0-9]/giu, "").toLocaleLowerCase()
  const provider = Object.keys(providers).find((name) => (
    name.replace(/[^a-z0-9]/giu, "").toLocaleLowerCase() === normalized
  ))
  if (!provider) return []
  return snapshot.presentation.provider_primary_fields.map(
    (field) => `/providers/${escapePointer(provider)}/${escapePointer(field)}`,
  )
}

export function primaryConfigPaths(snapshot: ConfigEditorSnapshot): string[] {
  return [...new Set([
    ...snapshot.presentation.primary_paths,
    ...providerPrimaryPaths(snapshot),
  ])]
}

function redactedContainerValue(
  value: JsonObject,
  path: string,
  secrets: Map<string, boolean>,
): JsonObject {
  const redacted = structuredClone(value)
  for (const secretPath of secrets.keys()) {
    if (secretPath.startsWith(`${path}/`)) {
      writeConfigValue(redacted, secretPath.slice(path.length), null)
    }
  }
  return redacted
}

function breadcrumb(parts: string[]): string {
  const visible = parts[0] === "agents" && parts[1] === "defaults" ? parts.slice(2) : parts.slice(1)
  return visible.map(humanize).join(" › ")
}

function isAdvanced(
  path: string,
  sectionId: string,
  primary: Set<string>,
  raw: boolean,
): boolean {
  if (raw) return true
  if (primary.has(path)) return false
  const parts = pointerParts(path)
  const name = parts.at(-1) || ""
  if (sectionId === "models") return true
  if (sectionId === "channels" && parts.length >= 2 && !SHARED_CHANNEL_FIELDS.has(parts[1] || "")) {
    return false
  }
  return !BASIC_FIELD_NAMES.has(name)
}

/** Flatten the complete schema-backed draft into editable leaves. */
export function buildConfigFields(snapshot: ConfigEditorSnapshot): ConfigField[] {
  const fields: ConfigField[] = []
  const secrets = new Map(snapshot.secrets.map((secret) => [secret.path, secret.configured]))
  const deprecated = new Set(snapshot.presentation.deprecated_paths)
  const primary = new Set(primaryConfigPaths(snapshot))
  const rootSchema = snapshot.schema

  const visit = (value: unknown, rawSchema: JsonObject, parts: string[]): void => {
    const schema = valueSchema(rawSchema, rootSchema)
    const properties = isObject(schema.properties) ? schema.properties : {}
    const path = `/${parts.map(escapePointer).join("/")}`
    const objectValue = isObject(value) ? value : null
    const hasFixedProperties = Object.keys(properties).length > 0
    if (hasFixedProperties) {
      const extensible = schema.additionalProperties === true || isObject(schema.additionalProperties)
      if (parts.length && extensible) {
        const section = sectionFor(path, snapshot.presentation.sections)
        if (section) {
          fields.push({
            path,
            label: "Advanced JSON",
            breadcrumb: `${breadcrumb(parts)} › Advanced JSON`,
            description: "Edit this extensible object directly to add plugin-defined settings.",
            sectionId: section.id,
            type: "json",
            value: redactedContainerValue(objectValue || {}, path, secrets),
            enumValues: [],
            nullable: false,
            secret: false,
            configured: false,
            deprecated: false,
            advanced: true,
            raw: true,
          })
        }
      }
      const source = objectValue || {}
      const keys = [...new Set([...Object.keys(properties), ...Object.keys(source)])]
      for (const key of keys) {
        const declared = isObject(properties[key]) ? properties[key] : null
        const additional = isObject(schema.additionalProperties) ? schema.additionalProperties : {}
        visit(source[key], declared || additional, [...parts, key])
      }
      return
    }
    if (parts.length === 0) return
    const section = sectionFor(path, snapshot.presentation.sections)
    if (!section) return
    const effectiveValue = value === undefined && "default" in schema ? schema.default : value
    const enumValues = Array.isArray(schema.enum)
      ? schema.enum
      : schemaChoices(rawSchema, rootSchema).flatMap((choice) => (
          Array.isArray(choice.enum) ? choice.enum : choice.const === undefined ? [] : [choice.const]
        ))
    const secret = secrets.has(path)
    fields.push({
      path,
      label: humanize(parts.at(-1) || ""),
      breadcrumb: breadcrumb(parts),
      description: typeof schema.description === "string" ? schema.description : "",
      sectionId: section.id,
      type: fieldType(rawSchema, effectiveValue, rootSchema),
      value: effectiveValue,
      enumValues,
      nullable: nullableSchema(rawSchema, rootSchema),
      secret,
      configured: secrets.get(path) === true,
      deprecated: deprecated.has(path),
      advanced: deprecated.has(path) || isAdvanced(path, section.id, primary, false),
      raw: false,
    })
  }

  const properties = isObject(rootSchema.properties) ? rootSchema.properties : {}
  for (const [key, value] of Object.entries(snapshot.config)) {
    const schema = isObject(properties[key]) ? properties[key] : {}
    visit(value, schema, [key])
  }
  return fields.sort((left, right) => left.path.localeCompare(right.path))
}

export function readConfigValue(config: JsonObject, path: string): unknown {
  let current: unknown = config
  for (const part of pointerParts(path)) {
    if (!isObject(current)) return undefined
    current = current[part]
  }
  return current
}

export function writeConfigValue(config: JsonObject, path: string, value: unknown): void {
  const parts = pointerParts(path)
  if (!parts.length) return
  let current = config
  for (const part of parts.slice(0, -1)) {
    const next = current[part]
    if (!isObject(next)) current[part] = {}
    current = current[part] as JsonObject
  }
  const key = parts.at(-1)
  if (key) current[key] = value
}

export function displayConfigValue(field: ConfigField): string {
  if (field.secret) return field.configured ? "••••••••" : field.value === "" ? "Will clear" : "Not set"
  if (field.value === null || field.value === undefined) return "Not set"
  if (field.type === "boolean") return field.value ? "On" : "Off"
  if (field.type === "json") {
    const text = JSON.stringify(field.value)
    return text.length > 52 ? `${text.slice(0, 49)}…` : text
  }
  const text = String(field.value)
  return text.length > 52 ? `${text.slice(0, 49)}…` : text
}

export function editorInitialValue(field: ConfigField): string {
  if (field.secret) return ""
  if (field.value === null || field.value === undefined) return ""
  return field.type === "json" ? JSON.stringify(field.value, null, 2) : String(field.value)
}

export function parseConfigValue(field: ConfigField, input: string): unknown {
  if (field.secret && !input) return undefined
  if (field.type === "json") {
    if (!input.trim() && field.nullable) return null
    try {
      return JSON.parse(input) as unknown
    } catch {
      throw new Error("Enter valid JSON.")
    }
  }
  if (field.type === "number") {
    if (!input.trim() && field.nullable) return null
    const value = Number(input)
    if (!Number.isFinite(value)) throw new Error("Enter a valid number.")
    return value
  }
  if (field.type === "boolean") return input === "true"
  if (!input && field.nullable) return null
  return input
}

export function cloneConfig(config: JsonObject): JsonObject {
  return structuredClone(config)
}
