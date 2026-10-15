import { BrandMarkBadge } from "@/components/brand/mark"
import { AgentWordmark } from "@/components/brand/wordmark"
import { welcomeMessage } from "@/lib/agent"

export const WELCOME_COPY = welcomeMessage()

export function EmptyState({
  title = WELCOME_COPY,
  detail
}: {
  title?: string
  detail?: string
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <BrandMarkBadge size={80} />
      <AgentWordmark size="lg" className="mt-5" />
      <p className="mt-4 max-w-sm text-base leading-7 text-ink">{title}</p>
      {detail ? (
        <p className="mt-2 max-w-sm text-sm leading-6 text-muted">{detail}</p>
      ) : null}
    </div>
  )
}
