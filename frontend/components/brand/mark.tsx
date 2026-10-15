import { cn } from "@/lib/cn"

const CLASSIC_SRC = "/brand/logo-classic.png"
const POSTER_SRC = "/brand/logo-poster.png"

type BrandMarkProps = {
  size?: number
  className?: string
  title?: string
}

function ThemedMark({
  size,
  className,
  alt,
  title,
  decorative
}: {
  size: number
  className?: string
  alt: string
  title?: string
  decorative?: boolean
}) {
  const imgClass = cn(
    "absolute inset-0 h-full w-full rounded-[22%] object-cover",
    className
  )

  return (
    <span
      className="relative inline-block shrink-0"
      style={{ width: size, height: size }}
      title={decorative ? undefined : title}
    >
      <img
        src={CLASSIC_SRC}
        width={size}
        height={size}
        alt={alt}
        aria-hidden={decorative ? true : undefined}
        className={cn(imgClass, "[[data-theme=poster]_&]:hidden")}
        draggable={false}
      />
      <img
        src={POSTER_SRC}
        width={size}
        height={size}
        alt=""
        aria-hidden
        className={cn(imgClass, "hidden [[data-theme=poster]_&]:block")}
        draggable={false}
      />
    </span>
  )
}

export function BrandMark({
  size = 32,
  className,
  title = "Broker"
}: BrandMarkProps) {
  const decorative = !title

  return (
    <ThemedMark
      size={size}
      className={className}
      alt={decorative ? "" : title}
      title={title}
      decorative={decorative}
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
    <ThemedMark
      size={size}
      className={cn("shadow-sm", className)}
      alt="Broker"
      title="Broker"
    />
  )
}
