import { createSupabaseServerClient } from "@/lib/supabase/server"
import { getDevSession } from "@/lib/auth/dev-session"

export type UserProfile = {
  id: string
  email: string | null
  name: string
  location: string
  mobile_number: string
  created_at: string
  updated_at: string
}

function getBackendUrl() {
  return (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "http://127.0.0.1:8000"
  )
}

export async function getAccessToken() {
  const devSession = await getDevSession()
  if (devSession) {
    return devSession.token
  }

  const supabase = await createSupabaseServerClient()
  const {
    data: { session }
  } = await supabase.auth.getSession()

  return session?.access_token ?? null
}

export async function getCurrentAuthIdentity() {
  const devSession = await getDevSession()
  if (devSession) {
    return {
      accessToken: devSession.token,
      email: devSession.email,
      isDev: true
    }
  }

  const supabase = await createSupabaseServerClient()
  const {
    data: { user }
  } = await supabase.auth.getUser()
  const {
    data: { session }
  } = await supabase.auth.getSession()

  if (!session?.access_token) return null

  return {
    accessToken: session.access_token,
    email: user?.email ?? null,
    isDev: false
  }
}

export async function fetchMyProfile(accessToken: string) {
  let response: Response

  try {
    response = await fetch(`${getBackendUrl()}/users/me`, {
      headers: {
        Authorization: `Bearer ${accessToken}`
      },
      cache: "no-store"
    })
  } catch (error) {
    throw new Error(
      `Could not reach BrokerAI backend at ${getBackendUrl()}. Make sure FastAPI is running.`
    )
  }

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Profile lookup failed with status ${response.status}`)
  }

  return (await response.json()) as UserProfile
}

export async function createMyProfile(
  accessToken: string,
  payload: {
    name: string
    location: string
    mobile_number: string
  }
) {
  let response: Response

  try {
    response = await fetch(`${getBackendUrl()}/users/me`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload),
      cache: "no-store"
    })
  } catch (error) {
    throw new Error(
      `Could not reach BrokerAI backend at ${getBackendUrl()}. Make sure FastAPI is running.`
    )
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : `Profile creation failed with status ${response.status}`
    throw new Error(detail)
  }

  return (await response.json()) as UserProfile
}
