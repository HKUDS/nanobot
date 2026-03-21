import { useState } from 'react'
import type { WsEvent, ViewMode } from '../types'
import AgentList from './Sidebar/AgentList'
import SessionList from './Sidebar/SessionList'
import ChannelList from './Sidebar/ChannelList'
import AgentDetail from './AgentView/AgentDetail'
import Timeline from './AgentView/Timeline'
import AgentSessionHistory from './AgentView/AgentSessionHistory'
import SessionHistory from './SessionView/SessionHistory'
import MessageInput from './SessionView/MessageInput'
import SystemDashboard from './SystemView/Dashboard'

interface Props {
  events: WsEvent[]
  connected: boolean
  onClearEvents: () => void
}

type AgentViewTab = 'timeline' | 'history'

export default function Layout({ events, connected, onClearEvents }: Props) {
  const [view, setView] = useState<ViewMode>('agents')
  const [selectedAgent, setSelectedAgent] = useState<string>('main')
  const [selectedSession, setSelectedSession] = useState<string | null>(null)
  const [agentTab, setAgentTab] = useState<AgentViewTab>('timeline')

  const handleSelectAgent = (name: string) => {
    setSelectedAgent(name)
    setView('agents')
    setAgentTab('timeline')
  }

  const handleSelectSession = (key: string) => {
    setSelectedSession(key)
    setView('sessions')
  }

  return (
    <div className="flex h-screen bg-slate-900">
      {/* Sidebar */}
      <aside className="w-[280px] shrink-0 border-r border-slate-700/50 flex flex-col bg-slate-900/80">
        {/* Logo */}
        <div className="px-4 py-4 border-b border-slate-700/50 flex items-center gap-2">
          <span className="text-2xl">🐈</span>
          <span className="text-lg font-semibold text-white">nanobot</span>
          <span
            className={`ml-auto w-2 h-2 rounded-full ${
              connected ? 'bg-emerald-400' : 'bg-red-400 animate-pulse'
            }`}
            title={connected ? 'Connected' : 'Disconnected'}
          />
        </div>

        {/* Navigation sections */}
        <div className="flex-1 overflow-y-auto py-3 space-y-5">
          <AgentList
            events={events}
            onSelect={handleSelectAgent}
            selected={view === 'agents' ? selectedAgent : null}
          />

          <SessionList
            onSelect={handleSelectSession}
            selected={view === 'sessions' ? selectedSession : null}
          />

          <ChannelList />
        </div>

        {/* Footer actions */}
        <div className="border-t border-slate-700/50 p-3 space-y-1">
          <button
            onClick={() => setView('system')}
            className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-colors flex items-center gap-2
              ${view === 'system' ? 'bg-slate-700/60 text-white' : 'text-slate-400 hover:bg-slate-800/50'}`}
          >
            <span>⚡</span> System
          </button>
          <button
            onClick={onClearEvents}
            className="w-full text-left px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors flex items-center gap-2"
          >
            <span>🗑️</span> Clear Timeline
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0">
        {view === 'system' && <SystemDashboard connected={connected} />}

        {view === 'agents' && (
          <>
            <AgentDetail agentName={selectedAgent} />

            {/* Tab bar */}
            <div className="flex border-b border-slate-700/50 px-4 bg-slate-800/30">
              <button
                onClick={() => setAgentTab('timeline')}
                className={`px-3 py-2 text-sm border-b-2 transition-colors ${
                  agentTab === 'timeline'
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-slate-400 hover:text-slate-300'
                }`}
              >
                Live Timeline
              </button>
              <button
                onClick={() => setAgentTab('history')}
                className={`px-3 py-2 text-sm border-b-2 transition-colors ${
                  agentTab === 'history'
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-slate-400 hover:text-slate-300'
                }`}
              >
                Session History
              </button>
            </div>

            {agentTab === 'timeline' ? (
              <Timeline events={events} agentFilter={selectedAgent} />
            ) : (
              <AgentSessionHistory agentName={selectedAgent} />
            )}

            <MessageInput agentName={selectedAgent} />
          </>
        )}

        {view === 'sessions' && selectedSession && (
          <SessionHistory sessionKey={selectedSession} />
        )}
      </main>
    </div>
  )
}
