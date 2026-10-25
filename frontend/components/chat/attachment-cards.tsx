"use client"

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"

import { IconX, Spinner } from "@/components/icons"
import { cn } from "@/lib/cn"
import type { BrokerAttachment } from "@/lib/api/broker"
import { MAX_UPLOAD_FILES } from "@/lib/local-attachments"
import { useAuthObjectUrl } from "@/lib/use-auth-object-url"

export type StackAttachment = {
  id: string
  kind: string
  content_type?: string | null
  original_filename?: string | null
  label?: string | null
  url?: string | null
  content_url?: string | null
  share_class?: string | null
}

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
  status?: "granted" | "denied" | string | null
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
    description?: string | null
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
  inverted = false,
  accessToken = null
}: {
  attachments: StackAttachment[]
  inverted?: boolean
  accessToken?: string | null
}) {
  const [preview, setPreview] = useState<{ src: string; name: string } | null>(
    null
  )
  if (!attachments.length) return null
  const images = attachments.filter(isImageAttachment)
  const rest = attachments.filter((item) => !isImageAttachment(item))

  return (
    <div className="space-y-2">
      {images.length > 0 ? (
        <div
          className={cn(
            "grid gap-1.5",
            images.length === 1
              ? "grid-cols-1 justify-items-start"
              : "grid-cols-2"
          )}
        >
          {images.map((item) => (
            <AuthenticatedImage
              key={item.id}
              attachment={item}
              inverted={inverted}
              accessToken={accessToken}
              compact={images.length > 1}
              onOpen={(src, name) => setPreview({ src, name })}
            />
          ))}
        </div>
      ) : null}
      {rest.map((item) => (
        <AttachmentChip
          key={item.id}
          attachment={item}
          inverted={inverted}
          accessToken={accessToken}
        />
      ))}
      {preview ? (
        <ImageLightbox
          src={preview.src}
          name={preview.name}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </div>
  )
}

function AuthenticatedImage({
  attachment,
  inverted,
  accessToken,
  compact = false,
  onOpen
}: {
  attachment: StackAttachment
  inverted: boolean
  accessToken?: string | null
  compact?: boolean
  onOpen: (src: string, name: string) => void
}) {
  const src = useAuthObjectUrl(attachment.content_url, accessToken)
  const name = attachment.label || "Photo"
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(
    null
  )
  const portrait = Boolean(natural && natural.height > natural.width)

  return (
    <button
      type="button"
      onClick={() => {
        if (src) onOpen(src, name)
      }}
      disabled={!src}
      aria-label={`View ${name}`}
      className={cn(
        "block overflow-hidden rounded-xl border-0 p-0 text-left",
        compact ? "w-full" : "w-fit max-w-full",
        inverted ? "bg-white/15 ring-1 ring-white/20" : "bg-canvas",
        src && "cursor-zoom-in"
      )}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={name}
          onLoad={(event) => {
            const image = event.currentTarget
            setNatural({
              width: image.naturalWidth,
              height: image.naturalHeight
            })
          }}
          className={cn(
            compact
              ? "h-36 w-full object-cover"
              : cn(
                  "h-auto max-w-full object-contain",
                  portrait ? "max-h-[28rem] w-auto" : "max-h-72 w-auto"
                )
          )}
        />
      ) : (
        <div
          className={cn(
            "flex items-center justify-center text-xs text-muted",
            compact ? "h-28 w-full" : "h-40 w-56"
          )}
        >
          Loading photo…
        </div>
      )}
    </button>
  )
}

function ImageLightbox({
  src,
  name,
  onClose
}: {
  src: string
  name: string
  onClose: () => void
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-ink/80 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={name}
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close photo"
        className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/15 text-white transition hover:bg-white/25"
      >
        <IconX />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={name}
        onClick={(event) => event.stopPropagation()}
        className="max-h-[90vh] max-w-full rounded-2xl object-contain shadow-2xl"
      />
    </div>,
    document.body
  )
}

export function AttachmentChip({
  attachment,
  inverted = false,
  accessToken = null
}: {
  attachment: StackAttachment
  inverted?: boolean
  accessToken?: string | null
}) {
  const fileSrc = useAuthObjectUrl(
    attachment.kind === "url" ? null : attachment.content_url,
    accessToken,
    attachment.kind !== "url"
  )
  const href = attachment.kind === "url" ? attachment.url : fileSrc
  const name =
    attachment.label || (attachment.kind === "url" ? "Link" : "File")
  const kindLabel = attachment.kind === "url" ? "Link" : fileKindLabel(attachment)
  const privateItem = attachment.share_class === "personal"

  return (
    <a
      href={href || undefined}
      target={href ? "_blank" : undefined}
      rel="noreferrer"
      className={cn(
        "flex min-w-0 items-center gap-3 rounded-xl px-3 py-2.5 text-sm",
        inverted
          ? "bg-white text-ink shadow-sm"
          : "border border-line bg-canvas text-ink"
      )}
    >
      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-canvas text-xs font-semibold text-brand"
        aria-hidden="true"
      >
        {attachment.kind === "url" ? "URL" : kindLabel.slice(0, 3).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{name}</span>
        <span className="block truncate text-xs text-muted">
          {privateItem ? `Private · ${kindLabel}` : kindLabel}
        </span>
      </span>
    </a>
  )
}

function fileKindLabel(attachment: StackAttachment): string {
  const type = (attachment.content_type || "").toLowerCase()
  const name = (attachment.original_filename || attachment.label || "").toLowerCase()
  if (type.includes("pdf") || name.endsWith(".pdf")) return "PDF"
  if (type.includes("word") || name.endsWith(".docx")) return "Document"
  if (type.startsWith("image/") || /\.(jpg|jpeg|png|webp|heic|heif)$/.test(name)) {
    return "Photo"
  }
  return "File"
}

export function AttachmentRequestCard({
  payload,
  uploading,
  onUpload
}: {
  payload: AttachmentRequestPayload
  uploading: boolean
  onUpload: (files: File[]) => void
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
          multiple
          accept="image/jpeg,image/png,image/webp,image/heic,.pdf,.docx"
          disabled={uploading}
          onChange={(event) => {
            const selected = Array.from(event.target.files || []).slice(
              0,
              MAX_UPLOAD_FILES
            )
            if (selected.length) onUpload(selected)
            event.target.value = ""
          }}
        />
        <span className="inline-flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-ink px-4 text-sm font-semibold text-surface transition hover:bg-user">
          {uploading ? <Spinner className="h-4 w-4" /> : null}
          {uploading ? "Uploading…" : "Upload"}
        </span>
      </label>
      <p className="text-xs text-muted">Up to {MAX_UPLOAD_FILES} files.</p>
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
  const resolved =
    payload.status === "granted" || payload.status === "denied"

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
          {resolved
            ? payload.status === "granted"
              ? "You allowed this photo to be shared."
              : "You kept this file private."
            : payload.reason ||
              "This looks personal. I need your OK before I share it."}
        </p>
      </div>
      {resolved ? null : (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => onGrant(true)}
            className="flex h-10 flex-1 items-center justify-center gap-2 rounded-xl bg-accent px-4 text-sm font-semibold text-surface transition hover:bg-accent-hover disabled:opacity-50"
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
      )}
    </div>
  )
}

export function AttachmentShareCard({
  payload,
  attachments,
  accessToken = null
}: {
  payload: AttachmentSharePayload
  attachments: BrokerAttachment[]
  accessToken?: string | null
}) {
  const visibleAttachments = attachments.length
    ? attachments
    : payload.attachments.map((item) => ({
        id: item.id,
        kind: item.kind,
        label: item.label,
        purpose: item.purpose,
        content_type: item.content_type,
        description: item.description,
        original_filename: item.original_filename,
        url: item.url
      }))
  const imageCount = visibleAttachments.filter(isImageAttachment).length
  const title = galleryHeading(
    payload.title,
    imageCount > 1 ? imageCount : visibleAttachments.length
  )

  return (
    <div className="w-full min-w-0 space-y-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Shared with you
        </div>
        {visibleAttachments.length > 1 ? (
          <div className="text-[11px] text-muted">
            {visibleAttachments.length} items
          </div>
        ) : null}
      </div>
      {title ? (
        <div className="text-[15px] font-semibold leading-5 text-ink">{title}</div>
      ) : null}
      <AttachmentStack attachments={visibleAttachments} accessToken={accessToken} />
    </div>
  )
}

function galleryHeading(title: string, count: number): string {
  const stripped = title.replace(/\s+photo\s+\d+\s*$/i, "").trim()
  if (count > 1 && stripped) return stripped
  return stripped || title
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
