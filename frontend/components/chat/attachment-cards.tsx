"use client"

import { Spinner } from "@/components/icons"
import { cn } from "@/lib/cn"
import type { BrokerAttachment } from "@/lib/api/broker"

export type AttachmentRequestPayload = {
  kind: "broker_attachment_request"
  version: 1
  request_id: string
  purpose: string
  suggested_share_class: string
  hint: string
  title: string
}

export type AttachmentPermissionPayload = {
  kind: "broker_attachment_permission"
  version: 1
  match_id: string
  attachment_id: string
  label: string
  purpose?: string | null
  reason?: string
}

export type AttachmentSharePayload = {
  kind: "broker_attachment_share"
  version: 1
  match_id: string
  title: string
  attachments: Array<{
    id: string
    kind: string
    label?: string | null
    purpose?: string | null
    content_type?: string | null
    original_filename?: string | null
    url?: string | null
  }>
}

export function isImageAttachment(attachment: {
  content_type?: string | null
  kind?: string
}) {
  return (attachment.content_type || "").startsWith("image/")
}

export function AttachmentStack({
  attachments,
  inverted = false
}: {
  attachments: BrokerAttachment[]
  inverted?: boolean
}) {
  if (!attachments.length) return null
  const images = attachments.filter(isImageAttachment)
  const rest = attachments.filter((item) => !isImageAttachment(item))

  return (
    <div className="space-y-2">
      {images.length > 0 ? (
        <div
          className={cn(
            "grid gap-2",
            images.length === 1 ? "grid-cols-1" : "grid-cols-2"
          )}
        >
          {images.map((item) => (
            <a
              key={item.id}
              href={item.content_url || "#"}
              target="_blank"
              rel="noreferrer"
              className="overflow-hidden rounded-xl bg-black/5"
            >
              {item.content_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={item.content_url}
                  alt={item.label || item.original_filename || "Photo"}
                  className="h-40 w-full object-cover"
                />
              ) : (
                <div className="flex h-24 items-center justify-center text-xs text-muted">
                  Photo
                </div>
              )}
            </a>
          ))}
        </div>
      ) : null}
      {rest.map((item) => (
        <AttachmentChip key={item.id} attachment={item} inverted={inverted} />
      ))}
    </div>
  )
}

export function AttachmentChip({
  attachment,
  inverted = false
}: {
  attachment: BrokerAttachment
  inverted?: boolean
}) {
  const href =
    attachment.kind === "url" ? attachment.url : attachment.content_url
  const name =
    attachment.label ||
    attachment.original_filename ||
    (attachment.kind === "url" ? "Link" : "File")
  const privateItem = attachment.share_class === "personal"

  return (
    <a
      href={href || undefined}
      target={href ? "_blank" : undefined}
      rel="noreferrer"
      className={cn(
        "flex min-w-0 items-center gap-2 rounded-xl px-3 py-2 text-sm",
        inverted
          ? "bg-white/10 text-white"
          : "border border-line bg-canvas text-ink"
      )}
    >
      <span className="min-w-0 truncate font-medium">{name}</span>
      {privateItem ? (
        <span
          className={cn(
            "ml-auto shrink-0 text-[10px] font-semibold uppercase tracking-wide",
            inverted ? "text-white/70" : "text-muted"
          )}
        >
          Private
        </span>
      ) : null}
    </a>
  )
}

export function AttachmentRequestCard({
  payload,
  uploading,
  onUpload
}: {
  payload: AttachmentRequestPayload
  uploading: boolean
  onUpload: (file: File) => void
}) {
  return (
    <div className="w-full min-w-56 space-y-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Upload needed
        </div>
        <div className="mt-1 text-base font-semibold text-ink">
          {payload.title || "File"}
        </div>
        {payload.hint ? (
          <p className="mt-1 text-sm leading-5 text-muted">{payload.hint}</p>
        ) : null}
      </div>
      <label className="block">
        <input
          type="file"
          className="sr-only"
          accept="image/jpeg,image/png,image/webp,image/heic,.pdf,.docx"
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUpload(file)
            event.target.value = ""
          }}
        />
        <span className="inline-flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-ink px-4 text-sm font-semibold text-surface transition hover:bg-user">
          {uploading ? <Spinner className="h-4 w-4" /> : null}
          {uploading ? "Uploading…" : "Upload"}
        </span>
      </label>
    </div>
  )
}

export function AttachmentPermissionCard({
  payload,
  busy,
  onGrant
}: {
  payload: AttachmentPermissionPayload
  busy: boolean
  onGrant: (granted: boolean) => void
}) {
  return (
    <div className="w-full min-w-56 space-y-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Permission
        </div>
        <div className="mt-1 text-base font-semibold text-ink">
          Share {payload.label || "this file"}?
        </div>
        <p className="mt-1 text-sm leading-5 text-muted">
          {payload.reason ||
            "This looks personal. I need your OK before I share it."}
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onGrant(true)}
          className="flex h-10 flex-1 items-center justify-center gap-2 rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-[#0c4d48] disabled:opacity-50"
        >
          {busy ? <Spinner className="h-4 w-4" /> : null}
          {busy ? "Sharing…" : "Allow"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onGrant(false)}
          className="h-10 flex-1 rounded-xl border border-line px-4 text-sm font-semibold text-ink transition hover:bg-canvas disabled:opacity-50"
        >
          Not now
        </button>
      </div>
    </div>
  )
}

export function AttachmentShareCard({
  payload,
  attachments
}: {
  payload: AttachmentSharePayload
  attachments: BrokerAttachment[]
}) {
  return (
    <div className="w-full min-w-56 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
        Shared with you
      </div>
      <div className="text-base font-semibold text-ink">{payload.title}</div>
      <AttachmentStack attachments={attachments} />
    </div>
  )
}

export function parseAttachmentRequest(
  content: string
): AttachmentRequestPayload | null {
  return parseKind(content, "broker_attachment_request")
}

export function parseAttachmentPermission(
  content: string
): AttachmentPermissionPayload | null {
  return parseKind(content, "broker_attachment_permission")
}

export function parseAttachmentShare(
  content: string
): AttachmentSharePayload | null {
  return parseKind(content, "broker_attachment_share")
}

function parseKind<T>(content: string, kind: string): T | null {
  try {
    const payload = JSON.parse(content) as { kind?: string; version?: number }
    if (payload.kind === kind && payload.version === 1) {
      return payload as T
    }
  } catch {
    return null
  }
  return null
}
