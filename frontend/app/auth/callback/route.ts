import { NextResponse } from "next/server"

import { createSupabaseServerClient } from "@/lib/supabase/server"

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
  const { error } = await supabase.auth.exchangeCodeForSession(code)

  if (error) {
    return redirectToLogin(error.message)
  }

  return NextResponse.redirect(`${origin}${nextPath}`)
}
