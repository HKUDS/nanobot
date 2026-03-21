import { useState, useRef } from 'react'
import { useApi } from '../../hooks/useApi'

interface Props {
  agentName: string
}

export default function MessageInput({ agentName }: Props) {
  const { sendMessage, loading } = useApi()
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = async () => {
    const msg = text.trim()
    if (!msg || loading) return
    setText('')
    try {
      await sendMessage(msg, agentName)
    } catch (e) {
      console.error('Failed to send:', e)
    }
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const placeholder = agentName === 'main'
    ? 'Send a message... (Enter to send)'
    : `Send to @${agentName}... (Enter to send)`

  return (
    <div className="border-t border-slate-700/50 px-4 py-3 bg-slate-800/30">
      <div className="flex gap-2 items-end">
        <textarea
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className="flex-1 bg-slate-800 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200
            placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50 resize-none"
          style={{ minHeight: '38px', maxHeight: '120px' }}
          onInput={(e) => {
            const target = e.target as HTMLTextAreaElement
            target.style.height = 'auto'
            target.style.height = Math.min(target.scrollHeight, 120) + 'px'
          }}
        />
        <button
          onClick={handleSend}
          disabled={!text.trim() || loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500
            text-white text-sm font-medium rounded-lg transition-colors shrink-0"
        >
          {loading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
