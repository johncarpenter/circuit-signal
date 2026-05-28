import { useEffect, useRef, useState } from 'react'
import { connectRunProgress, type ProgressEvent } from '../api/client'

export function useRunProgress(runId: string | undefined) {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  const latest = events[events.length - 1] ?? null

  useEffect(() => {
    if (!runId) return

    const ws = connectRunProgress(
      runId,
      (event) => {
        setEvents((prev) => [...prev, event])
      },
      () => {
        setConnected(false)
      },
    )

    ws.onopen = () => setConnected(true)
    wsRef.current = ws

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [runId])

  return { events, latest, connected }
}
