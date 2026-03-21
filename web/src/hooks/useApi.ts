import { useState, useCallback } from 'react'
import type { Agent, SessionInfo, SessionDetail, SystemStatus, ChannelStatus } from '../types'

const BASE = '/api'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export function useApi() {
  const [loading, setLoading] = useState(false)

  const getStatus = useCallback(() => fetchJson<SystemStatus>('/status'), [])

  const getAgents = useCallback(() => fetchJson<Agent[]>('/agents'), [])

  const getAgent = useCallback((name: string) => fetchJson<Agent>(`/agents/${name}`), [])

  const getAgentSession = useCallback((name: string) =>
    fetchJson<SessionDetail>(`/agents/${encodeURIComponent(name)}/session`), [])

  const getSessions = useCallback(() => fetchJson<SessionInfo[]>('/sessions'), [])

  const getSession = useCallback((key: string) =>
    fetchJson<SessionDetail>(`/sessions/${encodeURIComponent(key)}`), [])

  const clearSession = useCallback((key: string) =>
    fetchJson<{ status: string }>(`/sessions/${encodeURIComponent(key)}`, { method: 'DELETE' }), [])

  const getChannels = useCallback(() => fetchJson<ChannelStatus>('/channels'), [])

  const sendMessage = useCallback(async (content: string, agent: string = 'main') => {
    setLoading(true)
    try {
      return await fetchJson<{ status: string; session_key: string }>('/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, agent }),
      })
    } finally {
      setLoading(false)
    }
  }, [])

  return {
    getStatus, getAgents, getAgent, getAgentSession,
    getSessions, getSession, clearSession, getChannels,
    sendMessage, loading,
  }
}
