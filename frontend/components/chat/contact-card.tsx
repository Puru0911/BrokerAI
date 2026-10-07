"use client"

type ContactCardPayload = {
  kind: "broker_contact_card"
  version: 1
  match_id: string
  title: string
  contact: {
    name: string
    email: string | null
    gender?: string | null
    date_of_birth?: string | null
    mobile_number?: string | null
    location?: string | null
  }
  request: {
    title: string
    summary: string
    category: string | null
    request_type: string
  }
}

export function ContactCard({
  payload,
  connecting,
  connected,
  onConnect,
  onOpenChat
}: {
  payload: ContactCardPayload
  connecting: boolean
  connected: boolean
  onConnect: () => void
  onOpenChat?: () => void
}) {
  return (
    <div className="w-full min-w-56 space-y-4">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Match
        </div>
        <div className="mt-1 text-base font-semibold text-ink">
          {payload.contact.name}
        </div>
        <div className="text-xs text-muted">{payload.request.title}</div>
      </div>

      {connected ? (
        <button
          type="button"
          onClick={onOpenChat}
          className="h-10 w-full rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-[#0c4d48]"
        >
          Open chat
        </button>
      ) : (
        <button
          type="button"
          disabled={connecting}
          onClick={onConnect}
          className="h-10 w-full rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-[#0c4d48] disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
        >
          {connecting ? "Connecting…" : "Connect"}
        </button>
      )}
    </div>
  )
}

export type ConnectOfferPayload = {
  kind: "broker_connect_offer"
  version: 1
  offer_id?: string
  match_id: string
  prompt: string
  status?: string
  title?: string
}

export function parseConnectOffer(content: string): ConnectOfferPayload | null {
  try {
    const payload = JSON.parse(content) as Partial<ConnectOfferPayload>
    if (
      payload.kind === "broker_connect_offer" &&
      payload.version === 1 &&
      typeof payload.match_id === "string" &&
      typeof payload.prompt === "string"
    ) {
      return payload as ConnectOfferPayload
    }
  } catch {
    return null
  }
  return null
}

export function ConnectOfferCard({
  payload,
  busy,
  onAccept,
  onDismiss
}: {
  payload: ConnectOfferPayload
  busy: boolean
  onAccept: () => void
  onDismiss: () => void
}) {
  return (
    <div className="w-full space-y-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          {payload.title || "Introduction"}
        </div>
        <p className="mt-1 text-sm leading-6 text-ink">{payload.prompt}</p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onAccept}
          className="h-10 flex-1 rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-[#0c4d48] disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
        >
          {busy ? "Working…" : "Introduce us"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDismiss}
          className="h-10 rounded-xl px-4 text-sm font-medium text-muted transition hover:text-ink disabled:opacity-50"
        >
          Not yet
        </button>
      </div>
    </div>
  )
}

export function parseContactCard(content: string): ContactCardPayload | null {
  try {
    const payload = JSON.parse(content) as Partial<ContactCardPayload>
    if (
      payload.kind === "broker_contact_card" &&
      payload.version === 1 &&
      typeof payload.match_id === "string" &&
      payload.contact &&
      payload.request
    ) {
      return payload as ContactCardPayload
    }
  } catch {
    return null
  }
  return null
}
