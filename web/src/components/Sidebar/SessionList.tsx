import { useEffect, useState } from 'react'
import type { SessionInfo } from '../../types'
import { useApi } from '../../hooks/useApi'

interface Props {
  onSelect: (key: string) => void
  selected: string | null
}

export default function SessionList({ onSelect, selected }: Props) {
  const { getSessions } = useApi()
  const [sessions, setSessions] = useState<SessionInfo[]>([])

  useEffect(() => {
    getSessions().then(setSessions).catch(() => {})
    const timer = setInterval(() => {
      getSessions().then(setSessions).catch(() => {})
    }, 8000)
    return () => clearInterval(timer)
  }, [getSessions])

  const formatTime = (ts: string) => {
    if (!ts) return ''
    const d = new Date(ts)
    const now = new Date()
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  return (
    <div>
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-3">
        Sessions
      </h3>
      <div className="space-y-0.5 max-h-[300px] overflow-y-auto">
        {sessions.length === 0 && (
          <p className="text-xs text-slate-500 px-3">No sessions yet</p>
        )}
        {sessions.map((s) => {
          const isActive = selected === s.key
          const [channel, chatId] = s.key.split(':', 2)
          return (
            <button
              key={s.key}
              onClick={() => onSelect(s.key)}
              className={`w-full text-left px-3 py-1.5 rounded-lg flex items-center gap-2 text-sm transition-colors
                ${isActive ? 'bg-slate-700/60 text-white' : 'text-slate-300 hover:bg-slate-800/50'}`}
            >
              <span className="text-xs text-slate-500">{channel}</span>
              <span className="truncate flex-1">{chatId}</span>
              <span className="text-xs text-slate-500 shrink-0">
                {formatTime(s.updated_at || '')}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
