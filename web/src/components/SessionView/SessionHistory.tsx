import { useEffect, useState } from 'react'
import type { SessionDetail, SessionMessage } from '../../types'
import { useApi } from '../../hooks/useApi'

interface Props {
  sessionKey: string
}

export default function SessionHistory({ sessionKey }: Props) {
  const { getSession, clearSession } = useApi()
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [clearing, setClearing] = useState(false)

  useEffect(() => {
    getSession(sessionKey).then(setSession).catch(() => setSession(null))
  }, [sessionKey, getSession])

  const handleClear = async () => {
    if (!confirm('Clear this session?')) return
    setClearing(true)
    try {
      await clearSession(sessionKey)
      setSession(null)
    } finally {
      setClearing(false)
    }
  }

  if (!session) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        Loading session...
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-3">
        <div className="text-2xl">💬</div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-white">{session.key}</h2>
          <div className="text-xs text-slate-400">
            {session.message_count} messages · Updated {new Date(session.updated_at).toLocaleString()}
          </div>
        </div>
        <button
          onClick={handleClear}
          disabled={clearing}
          className="text-xs px-3 py-1.5 rounded bg-red-900/30 text-red-300 hover:bg-red-900/50 transition-colors"
        >
          Clear Session
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {session.messages.map((msg, idx) => (
          <MessageBubble key={idx} msg={msg} />
        ))}
      </div>
    </div>
  )
}

function MessageBubble({ msg }: { msg: SessionMessage }) {
  const isUser = msg.role === 'user'
  const isTool = msg.role === 'tool'

  const content =
    typeof msg.content === 'string'
      ? msg.content
      : msg.content
          ?.filter((b) => b.type === 'text')
          .map((b) => b.text)
          .join('\n') || ''

  if (isTool) {
    return (
      <div className="text-xs border border-slate-700/50 rounded px-3 py-2 bg-slate-800/30">
        <span className="text-violet-400 font-mono">{msg.tool_name || 'tool'}</span>
        <pre className="text-slate-400 mt-1 whitespace-pre-wrap max-h-[120px] overflow-y-auto">
          {content.slice(0, 500)}
        </pre>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? 'bg-blue-600/30 text-blue-100 border border-blue-500/20'
            : 'bg-slate-700/40 text-slate-200 border border-slate-600/20'
        }`}
      >
        {msg.tool_calls && msg.tool_calls.length > 0 && (
          <div className="text-xs text-amber-400 mb-1">
            🔧 {msg.tool_calls.map((tc) => tc.name).join(', ')}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words">{content}</div>
        {msg.timestamp && (
          <div className="text-xs text-slate-500 mt-1">
            {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </div>
    </div>
  )
}
