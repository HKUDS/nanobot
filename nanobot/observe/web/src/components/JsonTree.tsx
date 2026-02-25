import React, { useMemo, useState } from "react"

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

type StringFormat = "json" | "raw"

function previewScalar(v: unknown): string {
  if (v === null) return "null"
  if (v === undefined) return "undefined"
  if (typeof v === "string") {
    return JSON.stringify(v)
  }
  if (typeof v === "number" || typeof v === "boolean") return String(v)
  return String(v)
}

function renderScalar(
  v: unknown,
  stringFormat: StringFormat,
): React.ReactNode {
  if (typeof v === "string" && stringFormat === "raw") {
    return <pre className="jsonScalar jsonScalarPre">{v}</pre>
  }
  return previewScalar(v)
}

function keyCount(v: unknown): number {
  if (Array.isArray(v)) return v.length
  if (isPlainObject(v)) return Object.keys(v).length
  return 0
}

function Node(props: {
  value: unknown
  label?: string
  path: string
  collapsed: Set<string>
  toggle: (p: string) => void
  stringFormat: StringFormat
}) {
  const { value, label, path, collapsed, toggle, stringFormat } = props
  const isContainer = Array.isArray(value) || isPlainObject(value)
  const isCollapsed = collapsed.has(path)
  const showHeader = label !== undefined
  const scalarRow = (
    <div className="jsonRow">
      <span className="jsonScalar">{renderScalar(value, stringFormat)}</span>
    </div>
  )

  const header = showHeader ? (
    <div className="jsonRow">
      {isContainer ? (
        <button className="jsonToggle" type="button" onClick={() => toggle(path)}>
          {isCollapsed ? "▶" : "▼"}
        </button>
      ) : (
        <span className="jsonSpacer" />
      )}
      {label ? <span className="jsonKey">{label}</span> : null}
      {label ? <span className="jsonColon">:</span> : null}
      {isContainer ? (
        <span className="jsonMeta">
          {Array.isArray(value) ? "Array" : "Object"}({keyCount(value)})
        </span>
      ) : (
        <span className="jsonScalar">{renderScalar(value, stringFormat)}</span>
      )}
    </div>
  ) : null

  if (!isContainer) return header ?? scalarRow
  if (isCollapsed) return header

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return header
    }
    return (
      <div className="jsonNode">
        {header}
        <div className="jsonChildren">
          {value.map((item, idx) => (
            <Node
              key={`${path}.${idx}`}
              value={item}
              label={String(idx)}
              path={`${path}.${idx}`}
              collapsed={collapsed}
              toggle={toggle}
              stringFormat={stringFormat}
            />
          ))}
        </div>
      </div>
    )
  }

  const entries = Object.entries(value)
    .filter(([, v]) => {
      if (Array.isArray(v)) return v.length > 0
      if (isPlainObject(v)) return Object.keys(v).length > 0
      return true
    })
    .sort(([a], [b]) => a.localeCompare(b))
  if (entries.length === 0) {
    return header
  }
  return (
    <div className="jsonNode">
      {header}
      <div className="jsonChildren">
        {entries.map(([k, v]) => (
          <Node
            key={`${path}.${k}`}
            value={v}
            label={k}
            path={`${path}.${k}`}
            collapsed={collapsed}
            toggle={toggle}
            stringFormat={stringFormat}
          />
        ))}
      </div>
    </div>
  )
}

export default function JsonTree(props: {
  value: unknown
  defaultCollapsedDepth?: number
  stringFormat?: StringFormat
}) {
  const initial = useMemo(() => {
    const set = new Set<string>()
    const depth = props.defaultCollapsedDepth ?? 2

    const walk = (v: unknown, p: string, d: number) => {
      if (d >= depth && (Array.isArray(v) || isPlainObject(v))) set.add(p)
      if (Array.isArray(v)) {
        v.slice(0, 20).forEach((item, idx) => walk(item, `${p}.${idx}`, d + 1))
      } else if (isPlainObject(v)) {
        Object.entries(v)
          .slice(0, 30)
          .forEach(([k, child]) => walk(child, `${p}.${k}`, d + 1))
      }
    }

    walk(props.value, "$", 0)
    return set
  }, [props.defaultCollapsedDepth, props.value])

  const [collapsed, setCollapsed] = useState<Set<string>>(initial)

  const toggle = (p: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })
  }

  return (
    <div className="jsonRoot">
      <Node
        value={props.value}
        path="$"
        collapsed={collapsed}
        toggle={toggle}
        stringFormat={props.stringFormat ?? "json"}
      />
    </div>
  )
}
