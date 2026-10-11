"use client"

import { BrandMark } from "@/components/brand/mark"
import { StatusPill } from "@/components/chat/chat-header"
import { IconLogout, IconPlus, IconTrash, Spinner } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { connectionPreview, formatSessionTime, formatStatus } from "@/lib/chat-format"
import { cn } from "@/lib/cn"
import type { BrokerMatchLane, BrokerSession, ConnectionSummary } from "@/lib/api/broker"

export function SessionSidebar({
  open,
  userEmail,
  sessions,
  connections,
  activeSessionId,
  activeMatchId,
  activeConnectionId,
  creatingSession,
  deletingSessionId,
  onCreateSession,
  onSelectSession,
  onSelectMatch,
  onSelectConnection,
  onDeleteSession,
  emailNotify,
  emailNotifyBusy,
  onToggleEmailNotify,
  logoutAction
}: {
  open: boolean
  userEmail: string
  sessions: BrokerSession[]
  connections: ConnectionSummary[]
  activeSessionId: string | null
  activeMatchId: string | null
  activeConnectionId: string | null
  creatingSession: boolean
  deletingSessionId: string | null
  onCreateSession: () => void
  onSelectSession: (sessionId: string) => void
  onSelectMatch: (sessionId: string, matchId: string) => void
  onSelectConnection: (connectionId: string) => void
  onDeleteSession: (sessionId: string) => void
  emailNotify: boolean
  emailNotifyBusy: boolean
  onToggleEmailNotify: () => void
  logoutAction: (formData: FormData) => void | Promise<void>
}) {
  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-72 max-w-[86vw] flex-col border-r border-line bg-surface transition-transform duration-200 lg:static lg:h-screen lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex h-14 items-center gap-3 px-4">
        <BrandMark size={28} className="shrink-0 text-accent" />
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-tight text-ink">
            BrokerAI
          </div>
          <div className="truncate text-[11px] text-muted">{userEmail}</div>
        </div>
      </div>

      <div className="px-3 pb-3">
        <button
          onClick={onCreateSession}
          disabled={creatingSession}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-accent text-sm font-semibold text-surface transition hover:bg-[#0c4d48] disabled:opacity-50"
        >
          {creatingSession ? (
            <Spinner className="h-4 w-4" />
          ) : (
            <IconPlus />
          )}
          New request
        </button>
      </div>

      <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-2 pb-3">
        {connections.length > 0 ? (
          <section aria-label="Direct chats">
            <h2 className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Chats
            </h2>
            <nav className="space-y-0.5">
              {connections.map((connection) => {
                const isActive = connection.id === activeConnectionId
                const preview = connectionPreview(
                  connection.last_message?.content,
                  Boolean(connection.last_message?.attachments?.length)
                )

                return (
                  <button
                    key={connection.id}
                    onClick={() => onSelectConnection(connection.id)}
                    className={cn(
                      "flex w-full min-w-0 items-start gap-2 rounded-xl px-3 py-2.5 text-left transition",
                      isActive ? "bg-accent-soft" : "hover:bg-canvas"
                    )}
                  >
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-canvas text-xs font-semibold text-accent">
                      {initials(connection.peer.name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-sm font-medium text-ink">
                          {connection.peer.name}
                        </span>
                        <span className="shrink-0 font-sans text-[11px] tabular-nums text-muted">
                          {formatSessionTime(connection.updated_at)}
                        </span>
                      </span>
                      <span className="mt-0.5 flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-xs text-muted">
                          {preview}
                        </span>
                        {connection.unread_count > 0 ? (
                          <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-semibold text-surface">
                            {connection.unread_count > 9
                              ? "9+"
                              : connection.unread_count}
                          </span>
                        ) : null}
                      </span>
                    </span>
                  </button>
                )
              })}
            </nav>
          </section>
        ) : null}

        <section aria-label="Chat sessions">
          <h2 className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            Requests
          </h2>
          <nav className="space-y-0.5">
            {sessions.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs leading-5 text-muted">
                No requests yet. Start with whatever you need matched.
              </p>
            ) : (
              sessions.map((session) => {
                const lanes = session.matches ?? []
                const liveLanes = lanes.filter((match) => match.status !== "closed")
                const isActive =
                  session.id === activeSessionId && !activeConnectionId
                const unread = session.match_unread_count ?? 0

                return (
                  <div
                    key={session.id}
                    className={cn(
                      "group relative rounded-xl px-3 py-2.5 transition",
                      isActive && !activeMatchId
                        ? "bg-accent-soft"
                        : isActive
                          ? "bg-canvas"
                          : "hover:bg-canvas"
                    )}
                  >
                    <button
                      onClick={() => onSelectSession(session.id)}
                      className="w-full min-w-0 text-left"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-sm font-medium text-ink">
                          {session.title}
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          {unread > 0 ? (
                            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-semibold text-surface">
                              {unread > 9 ? "9+" : unread}
                            </span>
                          ) : null}
                          <span className="font-sans text-[11px] tabular-nums text-muted">
                            {formatSessionTime(session.updated_at)}
                          </span>
                        </span>
                      </div>
                      <div className="mt-0.5 line-clamp-1 pr-8 text-xs text-muted">
                        {session.summary || "No request details yet"}
                      </div>
                    </button>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <StatusPill
                        status={
                          liveLanes.length
                            ? `${liveLanes.length} match${liveLanes.length === 1 ? "" : "es"}`
                            : session.status
                        }
                      />
                      <button
                        type="button"
                        aria-label={`Delete ${session.title}`}
                        onClick={(event) => {
                          event.stopPropagation()
                          onDeleteSession(session.id)
                        }}
                        disabled={deletingSessionId === session.id}
                        className="rounded-lg p-1.5 text-muted transition hover:bg-danger-soft hover:text-danger disabled:opacity-50 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100"
                      >
                        {deletingSessionId === session.id ? (
                          <Spinner className="h-3.5 w-3.5" />
                        ) : (
                          <IconTrash />
                        )}
                      </button>
                    </div>
                    {lanes.length > 0 ? (
                      <div className="mt-2 space-y-0.5 border-t border-line/70 pt-2">
                        {lanes.map((match) => (
                          <SidebarMatchRow
                            key={match.id}
                            match={match}
                            active={
                              isActive && activeMatchId === match.id
                            }
                            onSelect={() => onSelectMatch(session.id, match.id)}
                          />
                        ))}
                      </div>
                    ) : null}
                  </div>
                )
              })
            )}
          </nav>
        </section>
      </div>

      <div className="border-t border-line p-3">
        <button
          type="button"
          onClick={onToggleEmailNotify}
          disabled={emailNotifyBusy}
          className="mb-1 flex h-10 w-full items-center justify-between gap-3 rounded-xl px-2 text-left text-sm text-ink transition hover:bg-canvas disabled:opacity-50"
        >
          <span>Email me when I'm away</span>
          <span
            aria-hidden
            className={cn(
              "relative h-5 w-9 shrink-0 rounded-full transition",
              emailNotify ? "bg-accent" : "bg-line"
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow-sm transition",
                emailNotify ? "left-4" : "left-0.5"
              )}
            />
          </span>
        </button>
        <form action={logoutAction}>
          <Button type="submit" variant="ghost" className="h-10 w-full justify-start text-muted">
            <IconLogout />
            Sign out
          </Button>
        </form>
      </div>
    </aside>
  )
}

function SidebarMatchRow({
  match,
  active,
  onSelect
}: {
  match: BrokerMatchLane
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition",
        active ? "bg-surface" : "hover:bg-surface/80"
      )}
    >
      <span
        className={cn(
          "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
          match.status === "closed"
            ? "bg-muted"
            : match.status === "connected" || match.status === "accepted"
              ? "bg-accent"
              : "bg-accent/60"
        )}
      />
      <span className="min-w-0 flex-1 overflow-hidden">
        <span className="flex min-w-0 items-center justify-between gap-2">
          <span className="min-w-0 truncate text-xs font-medium text-ink">
            {match.label}
          </span>
          {match.unread_count > 0 ? (
            <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold text-surface">
              {match.unread_count > 9 ? "9+" : match.unread_count}
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-muted">
          {match.waiting
            ? "Waiting on you"
            : match.status === "connected"
              ? "Connected"
              : match.summary || formatStatus(match.status)}
        </span>
      </span>
    </button>
  )
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
}
