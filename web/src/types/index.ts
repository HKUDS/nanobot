export interface Agent {
  name: string
  identity: string
  model: string
  aliases: string[]
  max_iterations: number
  tools?: string[]
}

export interface SessionInfo {
  key: string
  created_at: string
  updated_at: string
  path?: string
}

export interface SessionDetail {
  key: string
  created_at: string
  updated_at: string
  message_count: number
  messages: SessionMessage[]
}

export interface SessionMessage {
  role: string
  content: string | ContentBlock[]
  timestamp: string
  tool_calls?: { name: string; id: string }[]
  tool_name?: string
}

export interface ContentBlock {
  type: string
  text?: string
}

export interface SystemStatus {
  uptime_seconds: number
  model: string | null
  queue_inbound: number
  queue_outbound: number
  channels: string[]
  agents_count: number
}

export interface ChannelStatus {
  [name: string]: {
    enabled: boolean
    running: boolean
  }
}

// WebSocket event types
export interface WsEvent {
  type: string
  [key: string]: unknown
}

export interface TimelineEntry {
  id: string
  type: 'message_in' | 'message_out' | 'tool_call' | 'tool_result' | 'progress' | 'agent_status'
  agent?: string
  content?: string
  tool?: string
  args?: string
  preview?: string
  channel?: string
  chat_id?: string
  sender?: string
  status?: string
  timestamp: string
  is_tool_hint?: boolean
}

export type ViewMode = 'agents' | 'sessions' | 'channels' | 'system'
