import type { ReactNode } from "react"

import { BrandMarkBadge } from "@/components/brand/mark"

export function AuthShell({
  title,
  description,
  children
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-5 py-12">
      <section className="w-full max-w-[420px]">
        <div className="mb-8 flex flex-col items-center text-center">
          <BrandMarkBadge size={56} />
          <h1 className="mt-6 text-2xl font-semibold tracking-tight text-ink">
            {title}
          </h1>
          {description ? (
            <p className="mt-2 max-w-sm text-sm leading-6 text-muted">
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </section>
    </main>
  )
}
