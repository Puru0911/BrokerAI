import {
  brokerWebsocketUrl,
  type ConnectionMessage,
  type ConnectionSummary
} from "@/lib/api/broker"

export type BrokerSocketEvent =
  | { type: "hello"; user_id: string }
  | { type: "pong" }
  | { type: "connection.created"; connection: ConnectionSummary }
  | {
      type: "connection.message"
      connection: ConnectionSummary
      message: ConnectionMessage
    }

type SocketHandle = {
  close: () => void
  markRead: (connectionId: string) => void
}

export function connectBrokerSocket(
  accessToken: string,
  onEvent: (event: BrokerSocketEvent) => void,
  onStatus?: (status: "open" | "closed") => void
): SocketHandle {
  let closed = false
  let socket: WebSocket | null = null
  let retryDelay = 1000
  let retryTimer: number | null = null
  let pingTimer: number | null = null

  function clearTimers() {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
    if (pingTimer !== null) {
      window.clearInterval(pingTimer)
      pingTimer = null
    }
  }

  function open() {
    if (closed) return
    socket = new WebSocket(brokerWebsocketUrl(accessToken))
    socket.onopen = () => {
      retryDelay = 1000
      onStatus?.("open")
      pingTimer = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }))
        }
      }, 25000)
    }
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as BrokerSocketEvent
        if (payload && typeof payload.type === "string") {
          onEvent(payload)
        }
      } catch {
        return
      }
    }
    socket.onclose = () => {
      onStatus?.("closed")
      if (pingTimer !== null) {
        window.clearInterval(pingTimer)
        pingTimer = null
      }
      if (closed) return
      retryTimer = window.setTimeout(open, retryDelay)
      retryDelay = Math.min(retryDelay * 2, 15000)
    }
  }

  open()

  return {
    close() {
      closed = true
      clearTimers()
      socket?.close()
      socket = null
    },
    markRead(connectionId: string) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({
            type: "connection.read",
            connection_id: connectionId
          })
        )
      }
    }
  }
}
