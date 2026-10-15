"use client"

import { Suspense, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"

import { LoginShell, LoginShellFallback } from "@/components/layout/login-shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { IconGoogle, Spinner } from "@/components/icons"
import { devSignIn } from "@/app/login/actions"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"
import { cn } from "@/lib/cn"

const SUCCESS_STATUS = "Check your email for the sign-in link."

function LoginContent() {
  const supabase = useMemo(() => createSupabaseBrowserClient(), [])
  const searchParams = useSearchParams()
  const nextPath = searchParams.get("next") || "/app"
  const authError = searchParams.get("error")

  const [email, setEmail] = useState("")
  const [status, setStatus] = useState<string | null>(null)
  const [emailLoading, setEmailLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const showGoogle = process.env.NODE_ENV !== "production"
  const busy = emailLoading || googleLoading

  async function signInWithGoogle() {
    setStatus(null)
    setGoogleLoading(true)
    try {
      const origin = window.location.origin
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${origin}/auth/callback?next=${encodeURIComponent(
            nextPath
          )}`,
          scopes: [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/user.gender.read",
            "https://www.googleapis.com/auth/user.birthday.read"
          ].join(" "),
          queryParams: {
            access_type: "offline"
          }
        }
      })
      if (error) setStatus(error.message)
    } finally {
      setGoogleLoading(false)
    }
  }

  async function sendMagicLink() {
    setStatus(null)
    setEmailLoading(true)
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
      setStatus(SUCCESS_STATUS)
    } finally {
      setEmailLoading(false)
    }
  }

  const notice = status ?? authError
  const noticeIsSuccess = status === SUCCESS_STATUS

  return (
    <LoginShell>
      <div className="rounded-2xl border border-line bg-surface p-6 shadow-composer sm:p-7">
        <h2 className="text-xl font-semibold tracking-tight text-ink">
          Sign in
        </h2>
        <p className="mt-1.5 text-sm leading-6 text-muted">
          Enter your email and we’ll send a sign-in link.
        </p>

        <form
          className="mt-6 space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            void sendMagicLink()
          }}
        >
          <label className="block text-sm font-medium text-ink" htmlFor="email">
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-11"
          />
          <Button
            type="submit"
            disabled={busy || !email}
            className="h-11 w-full disabled:bg-accent/40 disabled:opacity-100"
          >
            {emailLoading ? <Spinner className="h-4 w-4" /> : null}
            Email me a sign-in link
          </Button>
        </form>

        {notice ? (
          <div
            role="status"
            className={cn(
              "mt-4 rounded-xl px-3.5 py-2.5 text-sm leading-6",
              noticeIsSuccess
                ? "bg-accent-soft text-accent"
                : "bg-danger-soft text-danger"
            )}
          >
            {notice}
          </div>
        ) : null}

        {showGoogle ? (
          <>
            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-line" />
              <div className="text-xs font-medium text-muted">or</div>
              <div className="h-px flex-1 bg-line" />
            </div>
            <Button
              onClick={signInWithGoogle}
              disabled={busy}
              variant="secondary"
              className="h-11 w-full"
            >
              {googleLoading ? (
                <Spinner className="h-4 w-4" />
              ) : (
                <IconGoogle className="h-[18px] w-[18px]" />
              )}
              Continue with Google
            </Button>
          </>
        ) : null}

        {process.env.NODE_ENV !== "production" ? (
          <form action={devSignIn} className="mt-6 border-t border-line pt-5">
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
      </div>
    </LoginShell>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginShellFallback />}>
      <LoginContent />
    </Suspense>
  )
}
