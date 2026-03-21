import { useWebSocket } from './hooks/useWebSocket'
import Layout from './components/Layout'

export default function App() {
  const { events, connected, clearEvents } = useWebSocket()

  return <Layout events={events} connected={connected} onClearEvents={clearEvents} />
}
