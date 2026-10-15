import type { ReactNode } from "react"

import { BrandLockup } from "@/components/brand/wordmark"
import { cn } from "@/lib/cn"

const HEADLINE = "Tell us what you need. We’ll find the right person."

const SUBHEAD =
  "Talk the way you would to a trusted fixer. The broker looks for a fit, then introduces you when both sides are ready."

const SUBHEAD_SHORT =
  "Talk to the broker. It finds a fit, then introduces you when both sides are ready."

const STEPS = [
  {
    title: "Say it in your own words",
    body: "No forms to fill. Describe the person, place, or deal you’re after."
  },
  {
    title: "The broker looks for a fit",
    body: "It searches quietly and only brings someone forward when both of you can help each other."
  },
  {
    title: "Meet when you both agree",
    body: "Your details stay private. Contacts are shared only after both of you say yes."
  }
] as const

function Glow() {
  return (
    <>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 -top-28 h-80 w-80 rounded-full bg-white/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-28 -right-16 h-72 w-72 rounded-full bg-black/25 blur-3xl"
      />
    </>
  )
}

function LoginBrand({ size }: { size: number }) {
  return (
    <BrandLockup
      markSize={size}
      nameSize={size >= 80 ? "lg" : "md"}
      inverse
      subtitle="Private broker"
    />
  )
}

function Steps({ compact = false }: { compact?: boolean }) {
  return (
    <ol className={compact ? "space-y-4" : "space-y-5"}>
      {STEPS.map((step, index) => (
        <li key={step.title} className="flex gap-3.5">
          <span
            className={cn(
              "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
              compact
                ? "bg-accent-soft text-accent"
                : "border border-white/25 text-surface"
            )}
          >
            {index + 1}
          </span>
          <div className="min-w-0">
            <div
              className={cn(
                "font-medium tracking-tight",
                compact ? "text-sm text-ink" : "text-[15px] text-surface"
              )}
            >
              {step.title}
            </div>
            <p
              className={cn(
                "mt-1 leading-6",
                compact ? "text-sm text-muted" : "text-sm text-surface/75"
              )}
            >
              {step.body}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}

export function LoginShell({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(28rem,0.9fr)]">
      <header className="relative bg-accent px-6 pb-8 pt-10 text-surface lg:hidden">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <Glow />
        </div>
        <div className="relative z-10">
          <LoginBrand size={64} />
          <h1 className="mt-6 text-[1.65rem] font-semibold leading-snug tracking-tight">
            {HEADLINE}
          </h1>
          <p className="mt-2 text-sm leading-6 text-surface/80">{SUBHEAD_SHORT}</p>
        </div>
      </header>

      <aside className="relative hidden bg-accent px-12 py-16 text-surface lg:flex lg:flex-col xl:px-16">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <Glow />
        </div>
        <div className="relative z-10 max-w-lg">
          <LoginBrand size={96} />
          <h1 className="mt-12 text-4xl font-semibold leading-[1.15] tracking-tight">
            {HEADLINE}
          </h1>
          <p className="mt-4 text-[15px] leading-7 text-surface/80">{SUBHEAD}</p>
          <div className="mt-12">
            <Steps />
          </div>
        </div>
      </aside>

      <section className="flex flex-col justify-center bg-canvas px-5 py-10 lg:px-12 lg:py-16">
        <div className="mx-auto w-full max-w-[420px]">
          {children}
          <div className="mt-10 lg:hidden">
            <Steps compact />
          </div>
        </div>
      </section>
    </main>
  )
}

export function LoginShellFallback() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-5 lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(28rem,0.9fr)] lg:items-stretch">
      <div className="hidden bg-accent lg:block" />
      <div className="text-sm text-muted lg:flex lg:items-center lg:justify-center">
        Loading…
      </div>
    </main>
  )
}
