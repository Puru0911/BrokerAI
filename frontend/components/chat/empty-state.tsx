import { BrandMarkBadge } from "@/components/brand/mark"

export const WELCOME_COPY =
  "Looking for someone or something specific? Tell me, and I'll get started."

export function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <BrandMarkBadge size={64} />
      <p className="mt-6 max-w-sm text-base leading-7 text-ink">{WELCOME_COPY}</p>
    </div>
  )
}
