import { cookies } from "next/headers"

const DEV_TOKEN_COOKIE = "brokerai_dev_token"
const DEV_EMAIL_COOKIE = "brokerai_dev_email"

export function isDevAuthEnabled() {
  return process.env.NODE_ENV !== "production"
}

export function createDevToken(email: string) {
  return `dev:${email.trim().toLowerCase()}`
}

export async function setDevSession(email: string) {
  if (!isDevAuthEnabled()) return

  const cookieStore = await cookies()
  const normalizedEmail = email.trim().toLowerCase()
  const options = {
    httpOnly: false,
    sameSite: "lax" as const,
    secure: false,
    path: "/",
    maxAge: 60 * 60 * 24
  }

  cookieStore.set(DEV_TOKEN_COOKIE, createDevToken(normalizedEmail), options)
  cookieStore.set(DEV_EMAIL_COOKIE, normalizedEmail, options)
}

export async function clearDevSession() {
  const cookieStore = await cookies()
  cookieStore.delete(DEV_TOKEN_COOKIE)
  cookieStore.delete(DEV_EMAIL_COOKIE)
}

export async function getDevSession() {
  if (!isDevAuthEnabled()) return null

  const cookieStore = await cookies()
  const token = cookieStore.get(DEV_TOKEN_COOKIE)?.value
  const email = cookieStore.get(DEV_EMAIL_COOKIE)?.value

  if (!token || !email) return null
  return { token, email }
}
