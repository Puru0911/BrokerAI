"use client"

import { formatStatus } from "@/lib/chat-format"
import { cn } from "@/lib/cn"
import type { BrokerMatchLane } from "@/lib/api/broker"

export function MatchLaneRail({
  requestTitle,
  matches,
  activeMatchId,
  requestBusy = false,
  busyMatchIds = [],
  onSelectRequest,
  onSelectMatch
}: {
  requestTitle: string
  matches: BrokerMatchLane[]
  activeMatchId: string | null
  requestBusy?: boolean
  busyMatchIds?: string[]
  onSelectRequest: () => void
  onSelectMatch: (matchId: string) => void
}) {
  if (matches.length === 0) return null

  const requestActive = activeMatchId === null
  const busy = new Set(busyMatchIds)

  return (
    <div className="shrink-0 border-b border-line bg-surface/70">
      <div
        role="tablist"
        aria-label="Request and match conversations"
        className="scrollbar-thin flex min-w-0 gap-1.5 overflow-x-auto px-4 py-2 sm:px-6"
      >
        <LaneTab
          label="Your request"
          detail={requestTitle}
          active={requestActive}
          busy={requestBusy}
          onClick={onSelectRequest}
        />
        {matches.map((match) => (
          <LaneTab
            key={match.id}
            label={match.label}
            detail={laneDetail(match)}
            active={activeMatchId === match.id}
            unread={match.unread_count}
            waiting={match.waiting}
            closed={match.status === "closed"}
            busy={busy.has(match.id)}
            onClick={() => onSelectMatch(match.id)}
          />
        ))}
      </div>
    </div>
  )
}

function laneDetail(match: BrokerMatchLane) {
  if (match.status === "connected") return "Connected"
  if (match.status === "accepted") return "Ready to connect"
  if (match.status === "closed") return match.close_reason ? formatStatus(match.close_reason) : "Closed"
  if (match.waiting) return "Waiting on you"
  return "In progress"
}

function LaneTab({
  label,
  detail,
  active,
  unread = 0,
  waiting = false,
  closed = false,
  busy = false,
  onClick
}: {
  label: string
  detail: string
  active: boolean
  unread?: number
  waiting?: boolean
  closed?: boolean
  busy?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex w-[16rem] max-w-[16rem] shrink-0 flex-col overflow-hidden rounded-xl border px-3 py-2 text-left transition",
        active
          ? "border-accent bg-accent-soft"
          : "border-line bg-surface hover:bg-canvas",
        closed && !active ? "opacity-70" : null
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
          {label}
        </span>
        {busy && !active ? (
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent" />
        ) : unread > 0 ? (
          <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-semibold text-surface">
            {unread > 9 ? "9+" : unread}
          </span>
        ) : waiting && !active ? (
          <span className="h-2 w-2 shrink-0 rounded-full bg-accent" />
        ) : null}
      </span>
      <span className="mt-0.5 w-full min-w-0 truncate text-[11px] text-muted">
        {detail}
      </span>
    </button>
  )
}
