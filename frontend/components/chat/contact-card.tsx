"use client"

type ContactCardPayload = {
  kind: "broker_contact_card"
  version: 1
  match_id: string
  title: string
  contact: {
    name: string
    email: string | null
    mobile_number: string
    location: string
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
  onConnect
}: {
  payload: ContactCardPayload
  connecting: boolean
  connected: boolean
  onConnect: () => void
}) {
  return (
    <div className="w-full min-w-56 space-y-4">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Contact
        </div>
        <div className="mt-1 text-base font-semibold text-ink">
          {payload.contact.name}
        </div>
        <div className="text-xs text-muted">{payload.request.title}</div>
      </div>

      <div className="grid gap-2 text-sm">
        <InfoRow label="Mobile" value={payload.contact.mobile_number} />
        {payload.contact.email ? (
          <InfoRow label="Email" value={payload.contact.email} breakAll />
        ) : null}
        <InfoRow label="Location" value={payload.contact.location} />
      </div>

      <p className="text-xs leading-5 text-muted">{payload.request.summary}</p>

      <button
        type="button"
        disabled={connecting || connected}
        onClick={onConnect}
        className="h-10 w-full rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-[#0c4d48] disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
      >
        {connected ? "Connected" : connecting ? "Connecting…" : "Connect"}
      </button>
    </div>
  )
}

function InfoRow({
  label,
  value,
  breakAll
}: {
  label: string
  value: string
  breakAll?: boolean
}) {
  return (
    <div className="rounded-xl bg-canvas px-3 py-2">
      <div className="text-[11px] font-medium text-muted">{label}</div>
      <div
        className={
          breakAll
            ? "break-all font-medium text-ink"
            : "break-words font-medium text-ink"
        }
      >
        {value}
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
