import { BrandMark, BrandMarkBadge } from "@/components/brand/mark"
import { AGENT_NAME, agentNameParts } from "@/lib/agent"
import { cn } from "@/lib/cn"

const NAME_SIZE = {
  sm: "text-base",
  md: "text-xl",
  lg: "text-2xl"
} as const

export function AgentWordmark({
  size = "md",
  inverse = false,
  className
}: {
  size?: keyof typeof NAME_SIZE
  inverse?: boolean
  className?: string
}) {
  const { lead, accent } = agentNameParts()

  return (
    <span
      aria-label={AGENT_NAME}
      className={cn(
        "inline-flex items-baseline font-semibold tracking-tight",
        NAME_SIZE[size],
        className
      )}
    >
      <span className={inverse ? "text-surface" : "text-ink"}>{lead}</span>
      {accent ? (
        <span className={inverse ? "text-accent-soft" : "text-accent"}>
          {accent}
        </span>
      ) : null}
    </span>
  )
}

export function BrandLockup({
  markSize = 40,
  nameSize = "md",
  inverse = false,
  subtitle,
  className
}: {
  markSize?: number
  nameSize?: keyof typeof NAME_SIZE
  inverse?: boolean
  subtitle?: string
  className?: string
}) {
  return (
    <div className={cn("flex min-w-0 items-center gap-3", className)}>
      {inverse ? (
        <BrandMarkBadge size={markSize} className="ring-1 ring-white/15" />
      ) : (
        <BrandMark size={markSize} />
      )}
      <div className="min-w-0">
        <AgentWordmark size={nameSize} inverse={inverse} />
        {subtitle ? (
          <div
            className={cn(
              "text-[11px] leading-4",
              inverse ? "text-surface/65" : "text-muted"
            )}
          >
            {subtitle}
          </div>
        ) : null}
      </div>
    </div>
  )
}
