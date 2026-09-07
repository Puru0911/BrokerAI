import type { InputHTMLAttributes } from "react"

import { cn } from "@/lib/cn"

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return (
    <input
      {...rest}
      className={cn(
        "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-muted/70",
        "focus:border-accent focus:ring-2 focus:ring-accent/20",
        "disabled:bg-canvas disabled:text-muted",
        className
      )}
    />
  )
}
