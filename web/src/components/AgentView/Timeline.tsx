import { useEffect, useRef, useState } from 'react'
import type { WsEvent } from '../../types'

interface Props {
  events: WsEvent[]
  agentFilter?: string
}

const ICONS: Record<string, string> = {
  message_in: '📩',
  message_out: '💬',
  tool_call: '🔧',
  tool_result: '✅',
  progress: '🤔',
  agent_status: '⚡',
}

const BG_COLORS: Record<string, string> = {
  message_in: 'border-blue-500/30 bg-blue-500/5',
  message_out: 'border-emerald-500/30 bg-emerald-500/5',
  tool_call: 'border-amber-500/30 bg-amber-500/5',
  tool_result: 'border-violet-500/30 bg-violet-500/5',
  progress: 'border-slate-500/30 bg-slate-500/5',
  agent_status: 'border-cyan-500/30 bg-cyan-500/5',
}

export default function Timeline({ events, agentFilter }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const filtered = agentFilter
    ? events.filter(
        (e) =>
          !e.agent || e.agent === agentFilter || e.type === 'message_in' || e.type === 'message_out'
      )
    : events

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [filtered.length])

  const toggleExpand = (idx: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const formatTime = (ts: string) => {
    if (!ts) return ''
    return new Date(ts).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  if (filtered.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        <div className="text-center">
          <div className="text-4xl mb-3">🐈</div>
          <p>Waiting for events...</p>
          <p className="text-xs mt-1">Send a message or interact via a channel</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-1.5">
      {filtered.map((event, idx) => {
        const icon = ICONS[event.type] || '📌'
        const colors = BG_COLORS[event.type] || 'border-slate-600/30 bg-slate-600/5'
        const expanded = expandedIds.has(idx)
        const isExpandable = event.type === 'tool_call' || event.type === 'tool_result'

        return (
          <div
            key={idx}
            className={`border rounded-lg px-3 py-2 ${colors} transition-all`}
            onClick={() => isExpandable && toggleExpand(idx)}
            style={{ cursor: isExpandable ? 'pointer' : 'default' }}
          >
            <div className="flex items-start gap-2">
              <span className="text-base shrink-0 mt-0.5">{icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-mono">
                    {formatTime(event.timestamp as string)}
                  </span>
                  {typeof event.agent === 'string' && event.agent !== 'main' ? (
                    <span className="text-xs bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded">
                      {event.agent}
                    </span>
                  ) : null}
                  {typeof event.channel === 'string' ? (
                    <span className="text-xs text-slate-500">
                      {event.channel}
                    </span>
                  ) : null}
                  {isExpandable && (
                    <span className="text-xs text-slate-500 ml-auto">
                      {expanded ? '▼' : '▶'}
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-sm text-slate-200">
                  {renderEventContent(event, expanded)}
                </div>
              </div>
            </div>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : String(v ?? '')
}

function renderEventContent(event: WsEvent, expanded: boolean): React.ReactNode {
  switch (event.type) {
    case 'message_in':
      return (
        <span>
          <span className="text-blue-300">{str(event.sender) || 'user'}</span>:{' '}
          {str(event.content)}
        </span>
      )
    case 'message_out':
      return <span className="text-emerald-200">{str(event.content)}</span>
    case 'tool_call':
      return (
        <div>
          <span className="font-mono text-amber-300">{str(event.tool)}</span>
          {expanded && event.args ? (
            <pre className="mt-1 text-xs text-slate-400 bg-slate-900/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
              {str(event.args)}
            </pre>
          ) : null}
        </div>
      )
    case 'tool_result':
      return (
        <div>
          <span className="text-violet-300">{str(event.tool)}</span>
          <span className="text-slate-400"> result</span>
          {expanded && event.preview ? (
            <pre className="mt-1 text-xs text-slate-400 bg-slate-900/50 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-[200px] overflow-y-auto">
              {str(event.preview)}
            </pre>
          ) : null}
        </div>
      )
    case 'progress':
      return <span className="text-slate-300 italic">{str(event.content)}</span>
    case 'agent_status':
      return (
        <span>
          Status: <span className={event.status === 'processing' ? 'text-amber-300' : 'text-emerald-300'}>
            {str(event.status)}
          </span>
        </span>
      )
    default:
      return <span className="text-slate-400">{JSON.stringify(event)}</span>
  }
}
