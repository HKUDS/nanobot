import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"
import MarkdownBlock from "./components/MarkdownBlock"
import JsonTree from "./components/JsonTree"
import { fetchTrace, fetchTraceList } from "./api"
import type { TraceEvent, TraceFile, TraceNode, TraceSummary } from "./types"
import { formatIso, isNonEmptyString, shortId, truncateText } from "./utils"

function stringifyTitle(v: unknown): string {
  if (typeof v === "string") return v
  try {
    return JSON.stringify(v, null, 0)
  } catch {
    return String(v ?? "")
  }
}

function traceTitleFromDetail(t: TraceFile): string {
  for (const ev of t.records) {
    if (ev.type === "input") {
      const content = (ev as any).content
      return truncateText(stringifyTitle(content), 20)
    }
  }
  return ""
}

function eventTypeLabel(type: string): string {
  const map: Record<string, string> = {
    input: "输入消息",
    model_call: "模型调用",
    tool_call: "工具调用",
    skill_use: "Skill 使用",
    subagent_spawn: "子Agent",
    response: "最终回复"
  }
  return map[type] ?? type
}

function buildTree(traces: TraceSummary[]): TraceNode[] {
  const map = new Map<string, TraceNode>()
  traces.forEach(t => {
    map.set(t.trace_id, { ...t, children: [] })
  })
  const roots: TraceNode[] = []
  map.forEach(node => {
    if (node.parent_trace_id && map.has(node.parent_trace_id)) {
      map.get(node.parent_trace_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  })
  const sortNodes = (nodes: TraceNode[]) => {
    nodes.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    nodes.forEach(n => sortNodes(n.children))
  }
  sortNodes(roots)
  return roots
}

function usePolling(intervalMs: number, enabled: boolean, tick: () => void) {
  useEffect(() => {
    if (!enabled) return
    const id = setInterval(() => tick(), intervalMs)
    return () => clearInterval(id)
  }, [enabled, intervalMs, tick])
}

function EventHeader(props: { event: TraceEvent }) {
  return (
    <div className="eventHeader">
      <span className="eventType">{eventTypeLabel(props.event.type)}</span>
      <span className="eventTime">{formatIso(props.event.timestamp)}</span>
    </div>
  )
}

function Collapsible(props: {
  className: string
  summary: React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(Boolean(props.defaultOpen))
  return (
    <details
      className={props.className}
      open={open}
      onToggle={e => {
        if (e.target !== e.currentTarget) return
        setOpen((e.currentTarget as HTMLDetailsElement).open)
      }}
    >
      <summary className="collapsibleSummary">
        <button
          className="jsonToggle collapsibleToggle"
          type="button"
          onClick={e => {
            e.preventDefault()
            e.stopPropagation()
            setOpen(v => !v)
          }}
        >
          {open ? "▼" : "▶"}
        </button>
        {props.summary}
      </summary>
      {props.children}
    </details>
  )
}

function EventWrapper(props: { event: TraceEvent; children: React.ReactNode }) {
  return (
    <Collapsible className="eventCard" summary={<EventHeader event={props.event} />}>
      <div className="eventBody">{props.children}</div>
    </Collapsible>
  )
}

function MetaGrid(props: { meta: Record<string, unknown> }) {
  return (
    <div className="metaGrid">
      {Object.entries(props.meta).map(([k, v]) => (
        <div className="metaRow" key={k}>
          <div className="metaKey">{k}</div>
          <div className="metaValue">
            {typeof v === "object" && v !== null ? (
              <JsonTree value={v} defaultCollapsedDepth={1} />
            ) : (
              String(v ?? "")
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function ModelCallEvent(props: { event: TraceEvent }) {
  const output = (props.event as any).output ?? {}
  const meta = {
    call_id: (props.event as any).call_id,
    model: (props.event as any).model,
    temperature: (props.event as any).temperature,
    max_tokens: (props.event as any).max_tokens,
    finish_reason: output.finish_reason,
    usage: output.usage
  }
  const input = {
    system_prompt: (props.event as any).system_prompt,
    messages: (props.event as any).messages
  }
  const outputBlock = {
    reasoning_content: output.reasoning_content,
    content: output.content,
    tool_calls: output.tool_calls
  }

  return (
    <EventWrapper event={props.event}>
      <Collapsible className="section" summary="元信息" defaultOpen>
        <MetaGrid meta={meta} />
      </Collapsible>
      <Collapsible className="section" summary="输入" defaultOpen>
        <div className="sectionBody">
          <Collapsible className="subSection" summary="SystemPrompt" defaultOpen>
            {isNonEmptyString(input.system_prompt) ? (
              <MarkdownBlock text={input.system_prompt} />
            ) : (
              <div className="empty">空</div>
            )}
          </Collapsible>
          <Collapsible className="subSection" summary="Messages" defaultOpen>
            <JsonTree value={input.messages ?? []} defaultCollapsedDepth={2} />
          </Collapsible>
        </div>
      </Collapsible>
      <Collapsible className="section" summary="输出" defaultOpen>
        <div className="sectionBody">
          <Collapsible className="subSection" summary="思考过程" defaultOpen>
            {isNonEmptyString(outputBlock.reasoning_content) ? (
              <MarkdownBlock text={outputBlock.reasoning_content} />
            ) : (
              <div className="empty">空</div>
            )}
          </Collapsible>
          <Collapsible className="subSection" summary="输出内容" defaultOpen>
            {isNonEmptyString(outputBlock.content) ? (
              <MarkdownBlock text={outputBlock.content} />
            ) : (
              <div className="empty">空</div>
            )}
          </Collapsible>
          {Array.isArray(outputBlock.tool_calls) && outputBlock.tool_calls.length > 0 ? (
            <Collapsible className="subSection" summary="ToolCalls" defaultOpen>
              <JsonTree value={outputBlock.tool_calls ?? []} defaultCollapsedDepth={2} />
            </Collapsible>
          ) : null}
        </div>
      </Collapsible>
    </EventWrapper>
  )
}

function DefaultEvent(props: { event: TraceEvent }) {
  const { type, timestamp, content, ...rest } = props.event as any
  if (type === "input") {
    const { role, media, ...next } = rest as Record<string, unknown>
    const value = Object.keys(next).length ? next : null
    return (
      <EventWrapper event={props.event}>
        {isNonEmptyString(content) ? <MarkdownBlock text={content} /> : null}
        {value ? <JsonTree value={value} defaultCollapsedDepth={2} /> : null}
      </EventWrapper>
    )
  }
  if (type === "response") {
    return (
      <EventWrapper event={props.event}>
        {isNonEmptyString(content) ? <MarkdownBlock text={content} /> : null}
      </EventWrapper>
    )
  }
  const value = Object.keys(rest).length ? rest : props.event
  return (
    <EventWrapper event={props.event}>
      {isNonEmptyString(content) ? <MarkdownBlock text={content} /> : null}
      <JsonTree value={value} defaultCollapsedDepth={2} />
    </EventWrapper>
  )
}

function TraceTree(props: {
  nodes: TraceNode[]
  selected: string | null
  onSelect: (id: string) => void
}) {
  if (!props.nodes.length) return <div className="empty">暂无 Trace</div>
  const renderNode = (node: TraceNode, depth: number) => {
    const isActive = node.trace_id === props.selected
    return (
      <div key={node.trace_id}>
        <button
          type="button"
          className={`traceItem ${isActive ? "active" : ""}`}
          style={{ paddingLeft: `${12 + depth * 16}px` }}
          onClick={() => props.onSelect(node.trace_id)}
        >
          <div className="traceTitle">{node.title ? node.title : shortId(node.trace_id)}</div>
          <div className="traceMeta">
            <span>{node.trace_type || "trace"}</span>
            <span>{formatIso(node.created_at)}</span>
          </div>
        </button>
        {node.children.map(child => renderNode(child, depth + 1))}
      </div>
    )
  }
  return <div>{props.nodes.map(n => renderNode(n, 0))}</div>
}

function TraceDetail(props: { trace: TraceFile | null }) {
  if (!props.trace) {
    return <div className="empty">请选择 Trace 查看详情</div>
  }
  const t = props.trace
  const title = traceTitleFromDetail(t)
  return (
    <div className="detail">
      <div className="detailBlock">
        <div className="detailHeader">
          <div className="detailTitle">{title ? title : `Trace ${t.trace_id}`}</div>
        </div>
        <MetaGrid
          meta={{
            trace_id: t.trace_id,
            trace_type: t.trace_type || "trace",
            ...(t.parent_trace_id ? { parent_trace_id: t.parent_trace_id } : {}),
            session_key: t.session_key,
            channel: t.channel,
            chat_id: t.chat_id,
            message_id: t.message_id,
            workspace: t.workspace,
            created_at: t.created_at,
            completed_at: t.completed_at
          }}
        />
      </div>
      <div className="events">
        {t.records.map((ev, idx) =>
          ev.type === "model_call" ? <ModelCallEvent event={ev} key={`${ev.type}-${idx}`} /> : <DefaultEvent event={ev} key={`${ev.type}-${idx}`} />
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [traceList, setTraceList] = useState<TraceSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedTrace, setSelectedTrace] = useState<TraceFile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const refreshLock = useRef(false)

  const tree = useMemo(() => buildTree(traceList), [traceList])

  const loadList = async () => {
    try {
      const list = await fetchTraceList()
      setTraceList(list)
      if (!selectedId && list.length > 0) {
        setSelectedId(list[0].trace_id)
      }
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  const loadDetail = async (id: string) => {
    try {
      const trace = await fetchTrace(id)
      setSelectedTrace(trace)
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  const refresh = useCallback(
    async (manual: boolean) => {
      if (refreshLock.current) return
      refreshLock.current = true
      if (manual) {
        setLoading(true)
        setError(null)
      }
      await loadList()
      if (selectedId) {
        await loadDetail(selectedId)
      }
      setLastRefresh(new Date())
      if (manual) {
        setLoading(false)
      }
      refreshLock.current = false
    },
    [selectedId]
  )

  useEffect(() => {
    refresh(true)
  }, [])

  useEffect(() => {
    if (selectedId) {
      loadDetail(selectedId)
    }
  }, [selectedId])

  usePolling(3000, true, () => {
    refresh(false)
  })

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebarHeader">
          <div className="sidebarTitle">Trace 列表</div>
          <div className="sidebarActions">
            <button className="btn" type="button" onClick={() => refresh(true)} disabled={loading}>
              {loading ? "刷新中" : "手动刷新"}
            </button>
            <div className="lastRefresh">
              上次刷新时间 {lastRefresh ? formatIso(lastRefresh.toISOString()) : "未刷新"}
            </div>
          </div>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <TraceTree nodes={tree} selected={selectedId} onSelect={setSelectedId} />
      </aside>
      <main className="main">
        <TraceDetail trace={selectedTrace} />
      </main>
    </div>
  )
}
