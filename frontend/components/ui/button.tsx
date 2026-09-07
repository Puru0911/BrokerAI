import type { ButtonHTMLAttributes, PropsWithChildren } from "react"

import { cn } from "@/lib/cn"

type Variant = "primary" | "secondary" | "ghost" | "danger"

export function Button(
  props: PropsWithChildren<
    ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }
  >
) {
  const { className, variant = "primary", ...rest } = props
  const variants: Record<Variant, string> = {
    primary:
      "bg-accent text-surface hover:bg-[#0c4d48] shadow-sm",
    secondary:
      "border border-line bg-surface text-ink hover:bg-black/[0.03]",
    ghost: "bg-transparent text-ink hover:bg-black/[0.04]",
    danger: "text-danger hover:bg-danger-soft"
  }

  return (
    <button
      {...rest}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        className
      )}
    />
  )
}
