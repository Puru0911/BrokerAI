import { NextResponse } from "next/server"

import { bootstrapGoogleProfile } from "@/lib/api/user-profile"
import { createSupabaseServerClient } from "@/lib/supabase/server"

function displayNameFromMetadata(metadata: Record<string, unknown> | undefined) {
  if (!metadata) return null
  for (const key of ["full_name", "name", "display_name"]) {
    const value = metadata[key]
    if (typeof value === "string" && value.trim().length >= 2) {
      return value.trim()
    }
  }
  return null
}

function isGoogleUser(user: {
  app_metadata?: { provider?: string }
  identities?: { provider?: string }[]
} | null) {
  if (!user) return false
  if (user.app_metadata?.provider === "google") return true
  return (user.identities ?? []).some((identity) => identity.provider === "google")
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get("code")
  const nextParam = searchParams.get("next") || "/app"
  const nextPath = nextParam.startsWith("/") ? nextParam : "/app"

  function redirectToLogin(error: string) {
    const loginUrl = new URL("/login", origin)
    loginUrl.searchParams.set("next", nextPath)
    loginUrl.searchParams.set("error", error)
    return NextResponse.redirect(loginUrl)
  }

  if (!code) {
    return redirectToLogin(
      "The magic link did not include an auth code. Check the Supabase redirect URL settings."
    )
  }

  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.auth.exchangeCodeForSession(code)

  if (error) {
    return redirectToLogin(error.message)
  }

  const session = data.session
  const user = data.user
  if (session?.access_token && isGoogleUser(user)) {
    await bootstrapGoogleProfile(session.access_token, {
      name: displayNameFromMetadata(
        user?.user_metadata as Record<string, unknown> | undefined
      ),
      googleAccessToken: session.provider_token
    })
  }

  return NextResponse.redirect(`${origin}${nextPath}`)
}
