import type { InputHTMLAttributes } from "react"

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return (
    <input
      {...rest}
      className={[
        "w-full rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm outline-none",
        "focus:border-zinc-400 focus:ring-2 focus:ring-zinc-200",
        className
      ]
        .filter(Boolean)
        .join(" ")}
    />
  )
}

