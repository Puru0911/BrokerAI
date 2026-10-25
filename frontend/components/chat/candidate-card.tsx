"use client"

import { ChatText } from "@/components/chat/chat-text"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/cn"

export type CandidateCardPayload = {
  kind?: "broker_candidate_card"
  version?: 1
  suggestion_id: string
  candidate_id: string
  preview: string
  status?: string
  label?: "strong_fit" | "close_fit"
  fits?: string[]
  still_open?: string[]
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
  busyId,
  onInterested,
  onSkip
}: {
  payload: CandidateDeckPayload
  busyId: string | null
  onInterested: (suggestionId: string) => void
  onSkip: (suggestionId: string) => void
}) {
  const items = payload.candidates
  const count = items.length

  return (
    <div className="w-full min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">
          {count === 1 ? "Match" : "Matches"}
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
              busy={busyId === item.suggestion_id}
              onInterested={() => onInterested(item.suggestion_id)}
              onSkip={() => onSkip(item.suggestion_id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

export function CandidateCard({
  payload,
  busy,
  onInterested,
  onSkip
}: {
  payload: CandidateCardPayload
  busy: boolean
  onInterested: () => void
  onSkip: () => void
}) {
  const status = payload.status || "presented"
  const inert = status === "interested" || status === "skipped"
  const closeFit = payload.label === "close_fit"
  const fits = (payload.fits || []).filter(Boolean)
  const stillOpen = (payload.still_open || []).filter(Boolean)

  return (
    <article
      className={cn(
        "flex h-full min-h-[10.5rem] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgb(0_0_0_/0.04)]",
        inert && "opacity-80"
      )}
    >
      <div className="flex flex-1 flex-col gap-3 p-3.5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          {closeFit ? "Close fit" : "Strong fit"}
        </p>
        {closeFit && (fits.length > 0 || stillOpen.length > 0) ? (
          <div className="flex flex-col gap-2 text-[13px] leading-5 text-ink">
            {fits.length > 0 ? (
              <p>
                <span className="font-medium text-muted">Fits. </span>
                <ChatText text={fits.join(" · ")} />
              </p>
            ) : null}
            {stillOpen.length > 0 ? (
              <p>
                <span className="font-medium text-muted">Still open. </span>
                <ChatText text={stillOpen.join(" · ")} />
              </p>
            ) : null}
          </div>
        ) : (
          <p className="line-clamp-5 text-[13px] leading-5 text-ink">
            <ChatText text={payload.preview} />
          </p>
        )}
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
