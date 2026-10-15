"use client"

import { useEffect, useState } from "react"

import { cn } from "@/lib/cn"

export const THEME_STORAGE_KEY = "brokerai-theme"

export type ThemeId = "classic" | "poster"

export function applyTheme(theme: ThemeId) {
  const root = document.documentElement
  if (theme === "poster") {
    root.dataset.theme = "poster"
  } else {
    delete root.dataset.theme
  }
}

export function ThemeSwitcher() {
  const [theme, setTheme] = useState<ThemeId>("classic")

  useEffect(() => {
    if (process.env.NODE_ENV === "production") return
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    const next: ThemeId = stored === "poster" ? "poster" : "classic"
    setTheme(next)
    applyTheme(next)
  }, [])

  if (process.env.NODE_ENV === "production") return null

  function choose(next: ThemeId) {
    setTheme(next)
    localStorage.setItem(THEME_STORAGE_KEY, next)
    applyTheme(next)
  }

  return (
    <div className="fixed right-3 top-3 z-[70] flex rounded-full border border-line bg-surface/90 p-0.5 shadow-composer backdrop-blur">
      <button
        type="button"
        onClick={() => choose("classic")}
        className={cn(
          "rounded-full px-3 py-1.5 text-xs font-semibold transition",
          theme === "classic" ? "bg-accent text-surface" : "text-muted hover:text-ink"
        )}
      >
        Current
      </button>
      <button
        type="button"
        onClick={() => choose("poster")}
        className={cn(
          "rounded-full px-3 py-1.5 text-xs font-semibold transition",
          theme === "poster" ? "bg-accent text-surface" : "text-muted hover:text-ink"
        )}
      >
        New
      </button>
    </div>
  )
}
