import { useEffect, useState } from 'react'
import type { Agent, WsEvent } from '../../types'
import { useApi } from '../../hooks/useApi'

interface Props {
  events: WsEvent[]
  onSelect: (name: string) => void
  selected: string | null
}

export default function AgentList({ events, onSelect, selected }: Props) {
  const { getAgents } = useApi()
  const [agents, setAgents] = useState<Agent[]>([])
  const [statuses, setStatuses] = useState<Record<string, string>>({})

  useEffect(() => {
    getAgents().then(setAgents).catch(() => {})
    const timer = setInterval(() => {
      getAgents().then(setAgents).catch(() => {})
    }, 10000)
    return () => clearInterval(timer)
  }, [getAgents])

  // Track agent status from WS events
  useEffect(() => {
    const last = events[events.length - 1]
    if (last?.type === 'agent_status') {
      setStatuses((prev) => ({
        ...prev,
        [last.agent as string]: last.status as string,
      }))
    }
  }, [events])

  return (
    <div>
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-3">
        Agents
      </h3>
      <div className="space-y-0.5">
        {agents.map((agent) => {
          const status = statuses[agent.name] || 'idle'
          const isActive = selected === agent.name
          return (
            <button
              key={agent.name}
              onClick={() => onSelect(agent.name)}
              className={`w-full text-left px-3 py-2 rounded-lg flex items-center gap-2 transition-colors text-sm
                ${isActive ? 'bg-slate-700/60 text-white' : 'text-slate-300 hover:bg-slate-800/50'}`}
            >
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  status === 'processing'
                    ? 'bg-amber-400 animate-pulse'
                    : 'bg-emerald-400'
                }`}
              />
              <span className="truncate font-medium">{agent.name}</span>
              <span className="text-xs text-slate-500 ml-auto truncate max-w-[80px]">
                {agent.model?.split('/').pop()}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
