import type { ButtonHTMLAttributes, PropsWithChildren } from "react"

type Variant = "primary" | "secondary" | "ghost"

export function Button(
  props: PropsWithChildren<
    ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }
  >
) {
  const { className, variant = "primary", ...rest } = props
  const base =
    "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition disabled:opacity-50"
  const variants: Record<Variant, string> = {
    primary: "bg-zinc-900 text-white hover:bg-zinc-800",
    secondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200",
    ghost: "bg-transparent text-zinc-900 hover:bg-zinc-100"
  }

  return (
    <button
      {...rest}
      className={[base, variants[variant], className].filter(Boolean).join(" ")}
    />
  )
}

