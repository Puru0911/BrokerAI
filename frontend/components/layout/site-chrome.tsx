import Link from "next/link"
import type { ReactNode } from "react"

import { BrandLockup } from "@/components/brand/wordmark"
import { cn } from "@/lib/cn"
import {
  PRIVACY_EMAIL,
  PRIVACY_PATH,
  PRODUCT_NAME,
  SITE_DOMAIN,
  SITE_OPERATOR,
  SUPPORT_EMAIL
} from "@/lib/site"

export function ctaClassName(variant: "primary" | "secondary" | "ghost") {
  const base =
    "inline-flex h-11 items-center justify-center rounded-xl px-5 text-sm font-medium transition"
  if (variant === "primary") {
    return cn(base, "bg-accent text-surface shadow-sm hover:bg-accent-hover")
  }
  if (variant === "secondary") {
    return cn(
      base,
      "border border-line bg-surface text-ink hover:bg-black/[0.03]"
    )
  }
  return cn(base, "text-ink hover:bg-black/[0.04]")
}

export function SiteHeader({ signedIn = false }: { signedIn?: boolean }) {
  const primaryHref = signedIn ? "/app" : "/login"
  const primaryLabel = signedIn ? "Open the app" : "Get started"
  const compactLabel = signedIn ? "Open" : "Start"
  const padForThemeSwitcher = process.env.NODE_ENV !== "production"

  return (
    <header className="sticky top-0 z-40 border-b border-line/80 bg-canvas/80 backdrop-blur-md">
      <div
        className={cn(
          "mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-5 sm:gap-4 sm:px-8",
          padForThemeSwitcher && "pr-[8.75rem] sm:pr-8"
        )}
      >
        <Link
          href="/"
          className="min-w-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
        >
          <div className="sm:hidden">
            <BrandLockup markSize={32} nameSize="sm" />
          </div>
          <div className="hidden sm:block">
            <BrandLockup markSize={36} nameSize="sm" subtitle="Private broker" />
          </div>
        </Link>
        <nav className="flex shrink-0 items-center gap-1 sm:gap-2">
          <Link
            href={PRIVACY_PATH}
            className="rounded-lg px-2.5 py-2 text-sm font-medium text-muted transition hover:text-ink sm:px-3"
          >
            Privacy
          </Link>
          {signedIn ? null : (
            <Link
              href="/login"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:text-ink sm:inline-flex"
            >
              Sign in
            </Link>
          )}
          <Link
            href={primaryHref}
            className={cn(
              ctaClassName("primary"),
              "h-9 shrink-0 whitespace-nowrap px-3.5 sm:h-11 sm:px-5"
            )}
          >
            <span className="sm:hidden">{compactLabel}</span>
            <span className="hidden sm:inline">{primaryLabel}</span>
          </Link>
        </nav>
      </div>
    </header>
  )
}

export function SiteFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 py-10 sm:px-8 sm:py-12 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-sm">
          <BrandLockup markSize={36} nameSize="sm" subtitle="Private broker" />
          <p className="mt-4 text-sm leading-6 text-muted">
            {PRODUCT_NAME} is a private AI broker operated by {SITE_OPERATOR} at{" "}
            {SITE_DOMAIN}.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-8 text-sm sm:grid-cols-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Product
            </div>
            <ul className="mt-3 space-y-2">
              <li>
                <Link href="/" className="text-ink hover:text-accent">
                  Home
                </Link>
              </li>
              <li>
                <Link href="/login" className="text-ink hover:text-accent">
                  Sign in
                </Link>
              </li>
              <li>
                <Link href="/app" className="text-ink hover:text-accent">
                  Open the app
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Legal
            </div>
            <ul className="mt-3 space-y-2">
              <li>
                <Link href={PRIVACY_PATH} className="text-ink hover:text-accent">
                  Privacy Policy
                </Link>
              </li>
            </ul>
          </div>
          <div className="col-span-2 sm:col-span-1">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Contact
            </div>
            <ul className="mt-3 space-y-2">
              <li>
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="text-ink hover:text-accent"
                >
                  {SUPPORT_EMAIL}
                </a>
              </li>
              <li>
                <a
                  href={`mailto:${PRIVACY_EMAIL}`}
                  className="text-ink hover:text-accent"
                >
                  {PRIVACY_EMAIL}
                </a>
              </li>
            </ul>
          </div>
        </div>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-5 text-xs leading-5 text-muted sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <p>
            © {year} {SITE_OPERATOR}.
          </p>
          <p>Introductions happen only when both sides say yes.</p>
        </div>
      </div>
    </footer>
  )
}

export function SiteShell({
  children,
  signedIn = false
}: {
  children: ReactNode
  signedIn?: boolean
}) {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <SiteHeader signedIn={signedIn} />
      <div className="flex-1">{children}</div>
      <SiteFooter />
    </div>
  )
}
