import { useEffect, useState } from 'react'
import type { ChannelStatus } from '../../types'
import { useApi } from '../../hooks/useApi'

export default function ChannelList() {
  const { getChannels } = useApi()
  const [channels, setChannels] = useState<ChannelStatus>({})

  useEffect(() => {
    getChannels().then(setChannels).catch(() => {})
    const timer = setInterval(() => {
      getChannels().then(setChannels).catch(() => {})
    }, 15000)
    return () => clearInterval(timer)
  }, [getChannels])

  const entries = Object.entries(channels)

  return (
    <div>
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-3">
        Channels
      </h3>
      {entries.length === 0 ? (
        <p className="text-xs text-slate-500 px-3">No channels enabled</p>
      ) : (
        <div className="space-y-0.5">
          {entries.map(([name, info]) => (
            <div
              key={name}
              className="px-3 py-1.5 flex items-center gap-2 text-sm text-slate-300"
            >
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  info.running ? 'bg-emerald-400' : 'bg-slate-600'
                }`}
              />
              <span>{name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
