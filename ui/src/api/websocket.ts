type MessageHandler = (data: unknown) => void

class WSManager {
  private ws: WebSocket | null = null
  private handlers: Map<string, MessageHandler[]> = new Map()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private url: string

  constructor() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${proto}//${window.location.host}/ws`
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return

    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      console.log('[WS] Connected')
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const handlers = this.handlers.get(msg.type) || []
        for (const h of handlers) h(msg.data)
      } catch {
        // ignore parse errors
      }
    }

    this.ws.onclose = () => {
      console.log('[WS] Disconnected, reconnecting in 2s...')
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, 2000)
  }

  on(type: string, handler: MessageHandler) {
    const list = this.handlers.get(type) || []
    list.push(handler)
    this.handlers.set(type, list)
  }

  off(type: string, handler: MessageHandler) {
    const list = this.handlers.get(type) || []
    this.handlers.set(
      type,
      list.filter((h) => h !== handler)
    )
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }
}

export const wsManager = new WSManager()
