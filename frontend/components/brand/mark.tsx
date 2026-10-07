import { cn } from "@/lib/cn"

const LOGO_SRC = "/brand/logo.png"

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
    <img
      src={LOGO_SRC}
      width={size}
      height={size}
      alt={decorative ? "" : title}
      title={decorative ? undefined : title}
      aria-hidden={decorative ? true : undefined}
      className={cn("rounded-[22%] object-cover", className)}
      draggable={false}
    />
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
    <img
      src={LOGO_SRC}
      width={size}
      height={size}
      alt="Broker"
      className={cn("rounded-[22%] object-cover shadow-sm", className)}
      style={{ width: size, height: size }}
      draggable={false}
    />
  )
}
