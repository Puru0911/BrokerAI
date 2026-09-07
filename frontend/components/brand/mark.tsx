import { cn } from "@/lib/cn"

type BrandMarkProps = {
  size?: number
  className?: string
  title?: string
}

export function BrandMark({
  size = 32,
  className,
  title = "Broker"
}: BrandMarkProps) {
  const decorative = !title

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : title}
    >
      {title ? <title>{title}</title> : null}
      <circle
        cx="12.25"
        cy="16"
        r="6.7"
        stroke="currentColor"
        strokeWidth="2.15"
      />
      <circle
        cx="19.75"
        cy="16"
        r="6.7"
        stroke="currentColor"
        strokeWidth="2.15"
      />
      <circle cx="16" cy="16" r="2.2" fill="currentColor" />
    </svg>
  )
}

export function BrandMarkBadge({
  size = 56,
  className
}: {
  size?: number
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-center rounded-2xl bg-accent text-surface shadow-sm",
        className
      )}
      style={{ width: size, height: size }}
    >
      <BrandMark size={Math.round(size * 0.58)} title="Broker" />
    </div>
  )
}
