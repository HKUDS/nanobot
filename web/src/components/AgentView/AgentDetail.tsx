import { useEffect, useState } from 'react'
import type { Agent } from '../../types'
import { useApi } from '../../hooks/useApi'

interface Props {
  agentName: string
}

export default function AgentDetail({ agentName }: Props) {
  const { getAgent } = useApi()
  const [agent, setAgent] = useState<Agent | null>(null)

  useEffect(() => {
    getAgent(agentName).then(setAgent).catch(() => setAgent(null))
  }, [agentName, getAgent])

  if (!agent) return null

  return (
    <div className="flex items-center gap-4 px-4 py-3 bg-slate-800/50 border-b border-slate-700/50">
      <div className="text-2xl">🤖</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-white">{agent.name}</h2>
          {agent.aliases?.length > 0 && (
            <span className="text-xs text-slate-400">
              aka {agent.aliases.join(', ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400 mt-0.5">
          <span>Model: <span className="text-slate-300">{agent.model}</span></span>
          <span>Max iterations: {agent.max_iterations}</span>
          {agent.tools && <span>{agent.tools.length} tools</span>}
        </div>
      </div>
      {agent.identity && (
        <div className="text-xs text-slate-400 max-w-[300px] truncate" title={agent.identity}>
          {agent.identity}
        </div>
      )}
    </div>
  )
}
