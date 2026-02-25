export type TraceEvent =
  | {
      type: string
      timestamp: string
      [key: string]: unknown
    }

export interface TraceFile {
  trace_id: string
  parent_trace_id: string | null
  trace_type?: string
  session_key?: string
  channel?: string
  chat_id?: string
  message_id?: string | null
  workspace?: string
  created_at?: string
  completed_at?: string | null
  records: TraceEvent[]
}

export interface TraceSummary {
  trace_id: string
  parent_trace_id: string | null
  trace_type?: string
  session_key?: string
  channel?: string
  chat_id?: string
  message_id?: string | null
  workspace?: string
  created_at?: string
  completed_at?: string | null
  records_count: number
  file_mtime: number
  title?: string
}

export interface TraceNode extends TraceSummary {
  children: TraceNode[]
}
