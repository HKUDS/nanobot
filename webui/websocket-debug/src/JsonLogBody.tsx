import type { ReactNode } from "react";

function JsonString({ value }: { value: string }) {
  return <span className="json-str">&quot;{value}&quot;</span>;
}

function JsonValue({ value, indent }: { value: unknown; indent: number }): ReactNode {
  const pad = indent * 0.5;
  if (value === null) {
    return <span className="json-null">null</span>;
  }
  if (typeof value === "boolean") {
    return <span className="json-bool">{value ? "true" : "false"}</span>;
  }
  if (typeof value === "number") {
    return <span className="json-num">{String(value)}</span>;
  }
  if (typeof value === "string") {
    return <JsonString value={value} />;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span>[]</span>;
    }
    return (
      <span>
        {"["}
        <br />
        {value.map((item, index) => (
          <span key={index} style={{ display: "block", paddingLeft: `${pad + 0.75}rem` }}>
            <JsonValue value={item} indent={indent + 1} />
            {index < value.length - 1 ? "," : ""}
          </span>
        ))}
        <span style={{ display: "block", paddingLeft: `${pad}rem` }}>{"]"}</span>
      </span>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return <span>{"{}"}</span>;
    }
    return (
      <span>
        {"{"}
        <br />
        {entries.map(([key, child], index) => (
          <span key={key} style={{ display: "block", paddingLeft: `${pad + 0.75}rem` }}>
            <span className="json-key">&quot;{key}&quot;</span>
            <span className="json-punct">: </span>
            <JsonValue value={child} indent={indent + 1} />
            {index < entries.length - 1 ? "," : ""}
          </span>
        ))}
        <span style={{ display: "block", paddingLeft: `${pad}rem` }}>{"}"}</span>
      </span>
    );
  }
  return <span className="json-unknown">{String(value)}</span>;
}

export function tryParseJsonObject(raw: string): unknown | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return null;
  }
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return null;
  }
}

export function JsonLogBody({ raw }: { raw: string }) {
  const parsed = tryParseJsonObject(raw);
  if (parsed === null) {
    return <span className="log-body-plain">{raw}</span>;
  }
  return (
    <div className="log-body-json">
      <JsonValue value={parsed} indent={0} />
    </div>
  );
}
