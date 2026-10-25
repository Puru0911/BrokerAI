import Link from "next/link"
import type { Metadata } from "next"

import { SiteShell, ctaClassName } from "@/components/layout/site-chrome"
import { ProductPreview } from "@/components/marketing/product-preview"
import { getPublicSession } from "@/lib/auth/public-session"
import { AGENT_NAME } from "@/lib/agent"
import { cn } from "@/lib/cn"
import { HEADLINE, STEPS, SUBHEAD, TRUST_LINE } from "@/lib/marketing-copy"
import { PRIVACY_PATH, PRODUCT_NAME, SITE_DESCRIPTION } from "@/lib/site"

export const metadata: Metadata = {
  title: {
    absolute: `${PRODUCT_NAME} — a private AI broker`
  },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" }
}

const PILLARS = [
  {
    title: "Your chat stays yours",
    body: "You talk to the broker in a private request. The other person does not see that thread, your files, or your contact details unless sharing is allowed later."
  },
  {
    title: "Screened, then you decide",
    body: "The broker looks for a fit and shows you a short brief. You tap Interested or Skip. A match lane opens only after you opt in."
  },
  {
    title: "Contacts on your say-so",
    body: "Name and how to reach you cross only after both of you accept an introduction. Until then, identity stays with the broker."
  }
] as const

const PROMISES = [
  {
    kicker: "No public profiles",
    body: "There is no directory to browse. People arrive through the broker, from a real request."
  },
  {
    kicker: "Any kind of ask",
    body: "A person, a place, a skill, a deal. Describe it in your own words. There is no category form."
  },
  {
    kicker: "Files stay gated",
    body: "You attach photos or documents in chat. Personal items need your OK before the other side sees them."
  }
] as const

export default async function HomePage() {
  const { signedIn } = await getPublicSession()
  const primaryHref = signedIn ? "/app" : "/login"
  const primaryLabel = signedIn ? "Open the app" : "Get started"

  return (
    <SiteShell signedIn={signedIn}>
      <main>
        <section className="relative overflow-hidden">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
          >
            <div className="absolute -left-24 -top-32 h-[28rem] w-[28rem] rounded-full bg-accent/10 blur-3xl" />
            <div className="absolute -right-16 top-24 h-72 w-72 rounded-full bg-accent/5 blur-3xl" />
          </div>
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-12 sm:px-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:gap-16 lg:pb-24 lg:pt-20">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
                Private AI broker
              </p>
              <h1 className="mt-4 max-w-xl text-[1.85rem] font-semibold leading-[1.18] tracking-tight text-ink sm:text-5xl sm:leading-[1.12]">
                <span className="block">Tell us what you need.</span>
                <span className="block">We’ll find the right person.</span>
              </h1>
              <p className="mt-5 max-w-lg text-base leading-7 text-muted sm:text-[17px]">
                {SUBHEAD}
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                <Link href={primaryHref} className={ctaClassName("primary")}>
                  {primaryLabel}
                </Link>
                <Link href="#how-it-works" className={ctaClassName("secondary")}>
                  How it works
                </Link>
              </div>
              <p className="mt-5 max-w-md text-sm leading-6 text-muted">
                {TRUST_LINE}
              </p>
            </div>
            <div className="relative">
              <div
                aria-hidden="true"
                className="absolute -inset-6 rounded-[2rem] bg-accent/10 blur-2xl"
              />
              <ProductPreview className="landing-float relative" />
            </div>
          </div>
        </section>

        <section className="relative bg-accent text-surface">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 overflow-hidden"
          >
            <div className="absolute -left-20 -top-24 h-72 w-72 rounded-full bg-white/10 blur-3xl" />
            <div className="absolute -bottom-24 -right-10 h-64 w-64 rounded-full bg-black/20 blur-3xl" />
          </div>
          <div
            id="how-it-works"
            className="relative mx-auto max-w-6xl scroll-mt-24 px-5 py-16 sm:px-8 sm:py-20"
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-surface/70">
              How it works
            </p>
            <h2 className="mt-3 max-w-xl text-3xl font-semibold tracking-tight">
              Three steps. You stay in control of the introduction.
            </h2>
            <ol className="mt-10 grid gap-6 md:grid-cols-3">
              {STEPS.map((step, index) => (
                <li
                  key={step.title}
                  className="rounded-2xl border border-white/15 bg-white/5 p-6"
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-full border border-white/25 text-sm font-semibold">
                    {index + 1}
                  </span>
                  <h3 className="mt-5 text-lg font-semibold tracking-tight">
                    {step.title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-surface/75">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
            Built for discretion
          </p>
          <h2 className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight text-ink">
            A go-between that works for you, then gets out of the way.
          </h2>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {PILLARS.map((pillar) => (
              <article
                key={pillar.title}
                className="rounded-2xl border border-line bg-surface p-6 shadow-sm"
              >
                <h3 className="text-lg font-semibold tracking-tight text-ink">
                  {pillar.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted">{pillar.body}</p>
              </article>
            ))}
          </div>
          <div className="mt-5 grid gap-5 md:grid-cols-3">
            {PROMISES.map((item) => (
              <article
                key={item.kicker}
                className="rounded-2xl border border-dashed border-line bg-canvas px-6 py-5"
              >
                <h3 className="text-sm font-semibold tracking-tight text-ink">
                  {item.kicker}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
            <div className="overflow-hidden rounded-[1.75rem] bg-accent px-6 py-12 text-surface sm:px-12 lg:flex lg:items-center lg:justify-between lg:gap-10">
              <div className="max-w-xl">
                <h2 className="text-3xl font-semibold tracking-tight">
                  Ready when you are.
                </h2>
                <p className="mt-3 text-[15px] leading-7 text-surface/80">
                  Sign in, tell {AGENT_NAME} what you need, and let the broker
                  look. Read how we handle Google account data, chats, and files
                  in the{" "}
                  <Link
                    href={PRIVACY_PATH}
                    className={cn(
                      "font-medium text-surface underline decoration-white/40 underline-offset-4 hover:decoration-white"
                    )}
                  >
                    Privacy Policy
                  </Link>
                  .
                </p>
              </div>
              <div className="mt-8 flex shrink-0 flex-col gap-3 sm:flex-row lg:mt-0">
                <Link
                  href={primaryHref}
                  className="inline-flex h-11 items-center justify-center rounded-xl bg-surface px-5 text-sm font-semibold text-accent shadow-sm hover:bg-white"
                >
                  {primaryLabel}
                </Link>
                <Link
                  href={PRIVACY_PATH}
                  className="inline-flex h-11 items-center justify-center rounded-xl border border-white/25 px-5 text-sm font-medium text-surface hover:bg-white/10"
                >
                  Privacy Policy
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>
    </SiteShell>
  )
}
