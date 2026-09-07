"use client"

import { useEffect, useState } from "react"

import { BrandMark } from "@/components/brand/mark"

const SHOW_DELAY_MS = 280

export function ThinkingIndicator({ active }: { active: boolean }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!active) {
      setVisible(false)
      return
    }

    const timeout = window.setTimeout(() => setVisible(true), SHOW_DELAY_MS)
    return () => window.clearTimeout(timeout)
  }, [active])

  if (!visible) return null

  return (
    <div className="flex justify-start" aria-live="polite" aria-label="Working">
      <div className="flex items-center gap-3 rounded-3xl rounded-bl-md border border-line bg-surface px-4 py-3">
        <BrandMark size={18} className="text-accent" title="" />
        <div className="flex items-center gap-1.5">
          <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-ink" />
          <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-ink" />
          <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-ink" />
        </div>
        <span className="text-xs font-medium text-muted">Working</span>
      </div>
    </div>
  )
}
