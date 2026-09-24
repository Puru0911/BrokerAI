"use client"

import { Suspense, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"

import { AuthShell } from "@/components/layout/auth-shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/icons"
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
    <AuthShell
      title="Welcome back"
      description="Sign in to continue to your matching workspace."
    >
      <div className="space-y-3">
        <Button
          onClick={signInWithGoogle}
          disabled={loading}
          className="h-11 w-full"
        >
          {loading ? <Spinner className="h-4 w-4" /> : null}
          Continue with Google
        </Button>
      </div>

      <div className="my-6 flex items-center gap-3">
        <div className="h-px flex-1 bg-line" />
        <div className="text-xs font-medium text-muted">or</div>
        <div className="h-px flex-1 bg-line" />
      </div>

      <div className="space-y-3">
        <label className="block text-sm font-medium text-ink" htmlFor="email">
          Email
        </label>
        <Input
          id="email"
          type="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Button
          onClick={sendMagicLink}
          disabled={loading || !email}
          variant="secondary"
          className="h-11 w-full"
        >
          Send magic link
        </Button>
      </div>

      {status || authError ? (
        <div className="mt-5 rounded-xl border border-line bg-canvas px-3 py-2 text-sm text-ink">
          {status ?? authError}
        </div>
      ) : null}

      {process.env.NODE_ENV !== "production" ? (
        <form action={devSignIn} className="mt-8 border-t border-line pt-5">
          <input type="hidden" name="email" value={email} />
          <input type="hidden" name="next" value={nextPath} />
          <Button
            type="submit"
            disabled={!email}
            variant="ghost"
            className="h-11 w-full text-muted"
          >
            Temporary local sign in
          </Button>
          <p className="mt-2 text-center text-xs leading-5 text-muted">
            Use only during local development if Supabase email rate limit is
            exceeded.
          </p>
        </form>
      ) : null}
    </AuthShell>
  )
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-canvas px-5">
          <div className="text-sm text-muted">Loading…</div>
        </main>
      }
    >
      <LoginContent />
    </Suspense>
  )
}
