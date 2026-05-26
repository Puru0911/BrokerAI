"use client"

import { Suspense, useMemo, useState } from "react"
import Image from "next/image"
import { useSearchParams } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { devSignIn } from "@/app/login/actions"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

function LoginContent() {
  const supabase = useMemo(() => createSupabaseBrowserClient(), [])
  const searchParams = useSearchParams()
  const nextPath = searchParams.get("next") || "/app"
  const authError = searchParams.get("error")

  const [email, setEmail] = useState("")
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function signInWithGoogle() {
    setStatus(null)
    setLoading(true)
    try {
      const origin = window.location.origin
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${origin}/auth/callback?next=${encodeURIComponent(
            nextPath
          )}`
        }
      })
      if (error) setStatus(error.message)
    } finally {
      setLoading(false)
    }
  }

  async function sendMagicLink() {
    setStatus(null)
    setLoading(true)
    try {
      const origin = window.location.origin
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${origin}/auth/callback?next=${encodeURIComponent(
            nextPath
          )}`
        }
      })
      if (error) {
        setStatus(error.message)
        return
      }
      setStatus("Check your email for the login link.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="grid min-h-screen bg-[#f6faf9] lg:grid-cols-[1.05fr_0.95fr]">
      <section className="relative hidden overflow-hidden bg-[#10275b] lg:block">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_28%_22%,rgba(14,173,166,0.35),transparent_34%),linear-gradient(135deg,#10275b_0%,#18386f_46%,#0eada6_100%)]" />
        <div className="relative flex h-full flex-col justify-between px-12 py-12 text-white">
          <Image
            src="/brokerai-logo.jpg"
            alt="BrokerAI logo"
            width={156}
            height={156}
            className="rounded-md bg-white object-cover shadow-xl"
            priority
          />
          <div className="max-w-xl space-y-5">
            <h1 className="text-5xl font-semibold leading-tight">BrokerAI</h1>
            <p className="text-lg leading-8 text-white/80">
              A private AI broker for requests, offers, matches, and deal-making
              conversations.
            </p>
          </div>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-5 py-10">
        <div className="w-full max-w-md rounded-md border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <header className="space-y-5">
            <Image
              src="/brokerai-logo.jpg"
              alt="BrokerAI logo"
              width={112}
              height={112}
              className="mx-auto rounded-md object-cover"
              priority
            />
            <div className="space-y-2 text-center">
              <h2 className="text-2xl font-semibold text-[#10275b]">
                Welcome back
              </h2>
              <p className="text-sm leading-6 text-slate-600">
                Sign in to continue to your matching workspace.
              </p>
            </div>
          </header>

          <div className="mt-8 space-y-3">
            <Button
              onClick={signInWithGoogle}
              disabled={loading}
              className="h-11 w-full bg-[#10275b] hover:bg-[#18386f]"
            >
              Continue with Google
            </Button>
          </div>

          <div className="my-6 flex items-center gap-3">
            <div className="h-px flex-1 bg-slate-200" />
            <div className="text-xs font-medium text-slate-500">or</div>
            <div className="h-px flex-1 bg-slate-200" />
          </div>

          <div className="space-y-3">
            <label
              className="block text-sm font-medium text-slate-700"
              htmlFor="email"
            >
              Email
            </label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-11 focus:border-[#0eada6] focus:ring-[#bff2ee]"
            />
            <Button
              onClick={sendMagicLink}
              disabled={loading || !email}
              className="h-11 w-full bg-[#0eada6] hover:bg-[#0b9690]"
            >
              Send magic link
            </Button>
          </div>

          {status || authError ? (
            <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              {status ?? authError}
            </div>
          ) : null}

          <form action={devSignIn} className="mt-5 border-t border-slate-200 pt-5">
            <input type="hidden" name="email" value={email} />
            <input type="hidden" name="next" value={nextPath} />
            <Button
              type="submit"
              disabled={!email}
              variant="secondary"
              className="h-11 w-full"
            >
              Temporary local sign in
            </Button>
            <p className="mt-2 text-center text-xs leading-5 text-slate-500">
              Use only during local development if Supabase email rate limit is
              exceeded.
            </p>
          </form>
        </div>
      </section>
    </main>
  )
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-[#f6faf9] px-5">
          <div className="w-full max-w-md rounded-md border border-slate-200 bg-white p-8 text-center text-sm text-slate-600 shadow-sm">
            Loading BrokerAI...
          </div>
        </main>
      }
    >
      <LoginContent />
    </Suspense>
  )
}
