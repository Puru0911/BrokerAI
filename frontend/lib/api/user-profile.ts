import { createSupabaseServerClient } from "@/lib/supabase/server"
import { getDevSession } from "@/lib/auth/dev-session"

export type UserProfile = {
  id: string
  email: string | null
  name: string
  gender: string | null
  date_of_birth: string | null
  location: string | null
  mobile_number: string | null
  notify_email?: boolean
  created_at: string
  updated_at: string
}

export type AuthIdentity = {
  accessToken: string
  email: string | null
  isDev: boolean
  provider: string | null
  fullName: string | null
  googleAccessToken: string | null
}

function getBackendUrl() {
  return (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "http://127.0.0.1:8000"
  )
}

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

export function isGoogleIdentity(identity: AuthIdentity) {
  return identity.provider === "google"
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

export async function getCurrentAuthIdentity(): Promise<AuthIdentity | null> {
  const devSession = await getDevSession()
  if (devSession) {
    return {
      accessToken: devSession.token,
      email: devSession.email,
      isDev: true,
      provider: null,
      fullName: null,
      googleAccessToken: null
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

  const identities = user?.identities ?? []
  const provider =
    user?.app_metadata?.provider === "google" ||
    identities.some((identity) => identity.provider === "google")
      ? "google"
      : (user?.app_metadata?.provider ?? null)

  return {
    accessToken: session.access_token,
    email: user?.email ?? null,
    isDev: false,
    provider,
    fullName: displayNameFromMetadata(
      user?.user_metadata as Record<string, unknown> | undefined
    ),
    googleAccessToken: session.provider_token ?? null
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
    gender: string
    date_of_birth: string
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

export async function bootstrapGoogleProfile(
  accessToken: string,
  payload: {
    name?: string | null
    googleAccessToken?: string | null
  }
) {
  let response: Response

  try {
    response = await fetch(`${getBackendUrl()}/users/me/google`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name: payload.name || null,
        google_access_token: payload.googleAccessToken || null
      }),
      cache: "no-store"
    })
  } catch {
    return null
  }

  if (!response.ok) {
    return null
  }

  return (await response.json()) as UserProfile
}
