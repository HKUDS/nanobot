import { useEffect, useState } from 'react'
import type { SystemStatus } from '../../types'
import { useApi } from '../../hooks/useApi'

interface Props {
  connected: boolean
}

export default function SystemDashboard({ connected }: Props) {
  const { getStatus } = useApi()
  const [status, setStatus] = useState<SystemStatus | null>(null)

  useEffect(() => {
    getStatus().then(setStatus).catch(() => {})
    const timer = setInterval(() => {
      getStatus().then(setStatus).catch(() => {})
    }, 5000)
    return () => clearInterval(timer)
  }, [getStatus])

  const formatUptime = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    return `${h}h ${m}m`
  }

  return (
    <div className="flex-1 p-6">
      <h2 className="text-xl font-semibold text-white mb-6">System Overview</h2>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="WebSocket"
          value={connected ? 'Connected' : 'Disconnected'}
          color={connected ? 'emerald' : 'red'}
        />
        <StatCard
          label="Uptime"
          value={status ? formatUptime(status.uptime_seconds) : '-'}
          color="blue"
        />
        <StatCard
          label="Agents"
          value={status?.agents_count?.toString() || '0'}
          color="violet"
        />
        <StatCard
          label="Queued"
          value={status ? `${status.queue_inbound} in / ${status.queue_outbound} out` : '-'}
          color="amber"
        />
      </div>

      {status && (
        <div className="space-y-4">
          <InfoRow label="Model" value={status.model || 'N/A'} />
          <InfoRow label="Channels" value={status.channels.join(', ') || 'None'} />
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color: string
}) {
  const colorMap: Record<string, string> = {
    emerald: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300',
    red: 'bg-red-500/10 border-red-500/20 text-red-300',
    blue: 'bg-blue-500/10 border-blue-500/20 text-blue-300',
    violet: 'bg-violet-500/10 border-violet-500/20 text-violet-300',
    amber: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
  }

  return (
    <div className={`border rounded-xl p-4 ${colorMap[color] || colorMap.blue}`}>
      <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-slate-400 w-20">{label}</span>
      <span className="text-slate-200 font-mono">{value}</span>
    </div>
  )
}
