"use client"

import { BrandMark } from "@/components/brand/mark"
import { StatusPill } from "@/components/chat/chat-header"
import { IconLogout, IconPlus, IconTrash, Spinner } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { formatSessionTime } from "@/lib/chat-format"
import { cn } from "@/lib/cn"
import type { BrokerSession } from "@/lib/api/broker"

export function SessionSidebar({
  open,
  userEmail,
  sessions,
  activeSessionId,
  creatingSession,
  deletingSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  logoutAction
}: {
  open: boolean
  userEmail: string
  sessions: BrokerSession[]
  activeSessionId: string | null
  creatingSession: boolean
  deletingSessionId: string | null
  onCreateSession: () => void
  onSelectSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
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

      <nav
        className="scrollbar-thin flex-1 space-y-0.5 overflow-y-auto px-2 pb-3"
        aria-label="Chat sessions"
      >
        {sessions.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs leading-5 text-muted">
            No requests yet. Start with whatever you need matched.
          </p>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === activeSessionId

            return (
              <div
                key={session.id}
                className={cn(
                  "group relative rounded-xl px-3 py-2.5 transition",
                  isActive ? "bg-accent-soft" : "hover:bg-canvas"
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
                    <span className="shrink-0 font-sans text-[11px] tabular-nums text-muted">
                      {formatSessionTime(session.updated_at)}
                    </span>
                  </div>
                  <div className="mt-0.5 line-clamp-1 pr-8 text-xs text-muted">
                    {session.summary || "No request details yet"}
                  </div>
                </button>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <StatusPill status={session.status} />
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
              </div>
            )
          })
        )}
      </nav>

      <form action={logoutAction} className="border-t border-line p-3">
        <Button type="submit" variant="ghost" className="h-10 w-full justify-start text-muted">
          <IconLogout />
          Sign out
        </Button>
      </form>
    </aside>
  )
}
