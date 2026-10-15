"use client"

import { useEffect, useRef, useState } from "react"

import { BrandLockup } from "@/components/brand/wordmark"
import { StatusPill } from "@/components/chat/chat-header"
import {
  IconChevronDown,
  IconLogout,
  IconPlus,
  IconTrash,
  Spinner
} from "@/components/icons"
import { connectionPreview, formatSessionTime, formatStatus } from "@/lib/chat-format"
import { cn } from "@/lib/cn"
import type { BrokerMatchLane, BrokerSession, ConnectionSummary } from "@/lib/api/broker"

export function SessionSidebar({
  open,
  userName,
  userEmail,
  sessions,
  connections,
  activeSessionId,
  activeMatchId,
  activeConnectionId,
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
  userName: string
  userEmail: string
  sessions: BrokerSession[]
  connections: ConnectionSummary[]
  activeSessionId: string | null
  activeMatchId: string | null
  activeConnectionId: string | null
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
      <div className="flex h-16 items-center px-4">
        <BrandLockup markSize={40} nameSize="md" />
      </div>

      <div className="px-3 pb-3">
        <button
          onClick={onCreateSession}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-accent text-sm font-semibold text-surface transition hover:bg-accent-hover"
        >
          <IconPlus />
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

      <SidebarProfileMenu
        userName={userName}
        userEmail={userEmail}
        emailNotify={emailNotify}
        emailNotifyBusy={emailNotifyBusy}
        onToggleEmailNotify={onToggleEmailNotify}
        logoutAction={logoutAction}
      />
    </aside>
  )
}

function SidebarProfileMenu({
  userName,
  userEmail,
  emailNotify,
  emailNotifyBusy,
  onToggleEmailNotify,
  logoutAction
}: {
  userName: string
  userEmail: string
  emailNotify: boolean
  emailNotifyBusy: boolean
  onToggleEmailNotify: () => void
  logoutAction: (formData: FormData) => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const displayName = userName.trim() || userEmail.split("@")[0] || "Signed in"

  useEffect(() => {
    if (!open) return

    function onPointer(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }

    document.addEventListener("mousedown", onPointer)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onPointer)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative border-t border-line p-3">
      {open ? (
        <div
          role="menu"
          className="absolute inset-x-3 bottom-full z-10 mb-2 overflow-hidden rounded-xl border border-line bg-surface shadow-composer"
        >
          <button
            type="button"
            role="menuitem"
            onClick={onToggleEmailNotify}
            disabled={emailNotifyBusy}
            className="flex h-11 w-full items-center justify-between gap-3 px-3 text-left text-sm text-ink transition hover:bg-canvas disabled:opacity-50"
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
          <form action={logoutAction} className="border-t border-line">
            <button
              type="submit"
              role="menuitem"
              className="flex h-11 w-full items-center gap-2 px-3 text-left text-sm text-muted transition hover:bg-canvas hover:text-ink"
            >
              <IconLogout />
              Sign out
            </button>
          </form>
        </div>
      ) : null}

      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-3 rounded-xl px-1.5 py-1.5 text-left transition hover:bg-canvas"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
          {initials(displayName, userEmail)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">
            {displayName}
          </span>
          <span className="block truncate text-[11px] text-muted">
            {userEmail}
          </span>
        </span>
        <IconChevronDown
          className={cn(
            "shrink-0 text-muted transition",
            open && "rotate-180"
          )}
        />
      </button>
    </div>
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

function initials(name: string, email?: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    const first = parts[0][0]
    const last = parts[parts.length - 1][0]
    return `${first}${last}`.toUpperCase()
  }
  if (parts.length === 1) {
    return parts[0][0].toUpperCase()
  }
  const local = email?.split("@")[0]?.trim()
  if (local) return local[0].toUpperCase()
  return "?"
}
