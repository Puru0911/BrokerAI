"use client"

import { ChatText } from "@/components/chat/chat-text"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/cn"
import { useAuthObjectUrl } from "@/lib/use-auth-object-url"

export type CandidateCardImage = {
  attachment_id: string
  share_class: "public" | "personal" | string
  label?: string | null
  content_url?: string | null
  blur_url?: string | null
  requestable?: boolean
}

export type CandidateCardPayload = {
  kind?: "broker_candidate_card"
  version?: 1
  suggestion_id: string
  candidate_id: string
  preview: string
  status?: string
  images?: CandidateCardImage[]
}

export type CandidateDeckPayload = {
  kind: "broker_candidate_cards"
  version: 1
  candidates: CandidateCardPayload[]
}

function asCandidate(value: Partial<CandidateCardPayload> | null | undefined): CandidateCardPayload | null {
  if (
    value &&
    typeof value.suggestion_id === "string" &&
    typeof value.preview === "string"
  ) {
    return value as CandidateCardPayload
  }
  return null
}

export function parseCandidateCard(content: string): CandidateCardPayload | null {
  try {
    const payload = JSON.parse(content) as Partial<CandidateCardPayload>
    if (payload.kind === "broker_candidate_card" && payload.version === 1) {
      return asCandidate(payload)
    }
  } catch {
    return null
  }
  return null
}

export function parseCandidateDeck(content: string): CandidateDeckPayload | null {
  try {
    const payload = JSON.parse(content) as {
      kind?: string
      version?: number
      candidates?: Partial<CandidateCardPayload>[]
    }
    if (
      payload.kind === "broker_candidate_cards" &&
      payload.version === 1 &&
      Array.isArray(payload.candidates)
    ) {
      const candidates = payload.candidates
        .map((item) => asCandidate(item))
        .filter((item): item is CandidateCardPayload => item !== null)
      if (candidates.length > 0) {
        return { kind: "broker_candidate_cards", version: 1, candidates }
      }
    }
  } catch {
    return null
  }
  const single = parseCandidateCard(content)
  if (!single) return null
  return { kind: "broker_candidate_cards", version: 1, candidates: [single] }
}

export function CandidateDeck({
  payload,
  accessToken,
  busyId,
  onInterested,
  onSkip,
  onRequestPhoto
}: {
  payload: CandidateDeckPayload
  accessToken: string | null
  busyId: string | null
  onInterested: (suggestionId: string) => void
  onSkip: (suggestionId: string) => void
  onRequestPhoto: (suggestionId: string, attachmentId: string) => void
}) {
  const items = payload.candidates
  const count = items.length

  return (
    <div className="w-full min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">
          {count === 1 ? "Possible match" : "Possible matches"}
        </p>
        {count > 1 ? (
          <p className="text-[11px] tabular-nums text-muted">{count}</p>
        ) : null}
      </div>
      <div
        className={cn(
          "flex gap-3",
          count > 1
            ? "overflow-x-auto pb-1 snap-x snap-mandatory scrollbar-thin sm:overflow-visible sm:pb-0"
            : "overflow-visible"
        )}
      >
        {items.map((item) => (
          <div
            key={item.suggestion_id}
            className={cn(
              "min-w-0",
              count === 1 && "w-full max-w-[20rem]",
              count === 2 &&
                "w-[min(17.5rem,82vw)] shrink-0 snap-start sm:w-1/2 sm:shrink",
              count >= 3 &&
                "w-[min(16.5rem,80vw)] shrink-0 snap-start sm:w-1/3 sm:shrink"
            )}
          >
            <CandidateCard
              payload={item}
              accessToken={accessToken}
              busy={busyId === item.suggestion_id}
              onInterested={() => onInterested(item.suggestion_id)}
              onSkip={() => onSkip(item.suggestion_id)}
              onRequestPhoto={(attachmentId) =>
                onRequestPhoto(item.suggestion_id, attachmentId)
              }
            />
          </div>
        ))}
      </div>
    </div>
  )
}

export function CandidateCard({
  payload,
  accessToken,
  busy,
  onInterested,
  onSkip,
  onRequestPhoto
}: {
  payload: CandidateCardPayload
  accessToken: string | null
  busy: boolean
  onInterested: () => void
  onSkip: () => void
  onRequestPhoto: (attachmentId: string) => void
}) {
  const status = payload.status || "presented"
  const inert = status === "interested" || status === "skipped"
  const images = payload.images || []
  const hero = images[0]
  const extra = images.slice(1, 3)

  return (
    <article
      className={cn(
        "flex h-full min-h-[17rem] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgb(0_0_0_/0.04)]",
        inert && "opacity-80"
      )}
    >
      <div className="relative bg-line/60">
        {hero ? (
          <SuggestionPhoto
            src={
              hero.share_class === "personal" ? hero.blur_url : hero.content_url
            }
            accessToken={accessToken}
            label={hero.label || "Photo"}
            blurred={hero.share_class === "personal"}
          />
        ) : (
          <div className="flex h-40 items-center justify-center text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
            No photo
          </div>
        )}
        {hero?.share_class === "personal" && hero.requestable && !inert ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onRequestPhoto(hero.attachment_id)}
            className="absolute bottom-2 right-2 rounded-full bg-surface/95 px-2.5 py-1 text-[11px] font-medium text-ink shadow-sm backdrop-blur-sm hover:bg-surface disabled:opacity-50"
          >
            Request photo
          </button>
        ) : null}
      </div>
      {extra.length > 0 ? (
        <div className="grid grid-cols-2 gap-px bg-line">
          {extra.map((image) => (
            <div key={image.attachment_id} className="relative h-16 bg-line/60">
              <SuggestionPhoto
                src={
                  image.share_class === "personal"
                    ? image.blur_url
                    : image.content_url
                }
                accessToken={accessToken}
                label={image.label || "Photo"}
                blurred={image.share_class === "personal"}
                compact
              />
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex flex-1 flex-col gap-3 p-3.5">
        <p className="line-clamp-4 text-[13px] leading-5 text-ink">
          <ChatText text={payload.preview} />
        </p>
        <div className="mt-auto">
          {inert ? (
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
              {status === "interested" ? "Opened" : "Skipped"}
            </p>
          ) : (
            <div className="flex gap-2">
              <Button
                type="button"
                disabled={busy}
                className="h-9 flex-1 text-[13px]"
                onClick={onInterested}
              >
                {busy ? "Working…" : "Interested"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                className="h-9 px-3 text-[13px] text-muted"
                onClick={onSkip}
              >
                Skip
              </Button>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

function SuggestionPhoto({
  src,
  accessToken,
  label,
  blurred,
  compact = false
}: {
  src: string | null | undefined
  accessToken: string | null
  label: string
  blurred: boolean
  compact?: boolean
}) {
  const objectUrl = useAuthObjectUrl(src, accessToken)
  if (!objectUrl) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-line text-[11px] text-muted",
          compact ? "h-16 w-full" : "h-40 w-full"
        )}
      >
        Photo
      </div>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={objectUrl}
      alt={label}
      className={cn(
        "w-full object-cover",
        compact ? "h-16" : "h-40",
        blurred && "blur-md scale-105"
      )}
    />
  )
}
