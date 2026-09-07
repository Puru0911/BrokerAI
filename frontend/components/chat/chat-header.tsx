import { IconMenu } from "@/components/icons"
import { formatStatus } from "@/lib/chat-format"
import { cn } from "@/lib/cn"

export function ChatHeader({
  title,
  status,
  onOpenSessions
}: {
  title: string
  status: string
  onOpenSessions: () => void
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur-sm sm:px-6">
      <button
        aria-label="Open sessions"
        onClick={onOpenSessions}
        className="flex h-9 w-9 items-center justify-center rounded-xl border border-line text-ink transition hover:bg-canvas lg:hidden"
      >
        <IconMenu />
      </button>
      <div className="min-w-0">
        <h1 className="truncate text-[15px] font-semibold tracking-tight text-ink sm:text-base">
          {title}
        </h1>
        <p className="truncate text-xs text-muted">{formatStatus(status)}</p>
      </div>
    </header>
  )
}

export function StatusPill({
  status,
  className
}: {
  status: string
  className?: string
}) {
  const tone =
    status === "matching" || status === "mediation"
      ? "bg-accent-soft text-accent"
      : "bg-canvas text-muted"

  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        tone,
        className
      )}
    >
      {formatStatus(status)}
    </span>
  )
}
