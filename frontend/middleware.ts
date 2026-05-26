import { NextResponse, type NextRequest } from "next/server"
import { createServerClient } from "@supabase/ssr"

export async function middleware(request: NextRequest) {
  const devToken = request.cookies.get("brokerai_dev_token")?.value
  const hasDevSession =
    process.env.NODE_ENV !== "production" && devToken?.startsWith("dev:")
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!url || !anonKey) {
    return NextResponse.next()
  }

  let response = NextResponse.next({ request })

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value, options }) => {
          request.cookies.set(name, value)
          response.cookies.set(name, value, options)
        })
      }
    }
  })

  const {
    data: { user }
  } = await supabase.auth.getUser()

  const isProtected =
    request.nextUrl.pathname.startsWith("/app") ||
    request.nextUrl.pathname.startsWith("/profile")
  const isAuthRoute =
    request.nextUrl.pathname.startsWith("/login") ||
    request.nextUrl.pathname.startsWith("/auth/callback")

  if (isProtected && !user && !hasDevSession && !isAuthRoute) {
    const redirectUrl = request.nextUrl.clone()
    redirectUrl.pathname = "/login"
    redirectUrl.searchParams.set("next", request.nextUrl.pathname)
    return NextResponse.redirect(redirectUrl)
  }

  return response
}

export const config = {
  matcher: ["/app/:path*", "/profile/:path*"]
}
