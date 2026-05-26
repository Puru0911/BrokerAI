"use server"

import { redirect } from "next/navigation"

import { setDevSession } from "@/lib/auth/dev-session"

export async function devSignIn(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim().toLowerCase()
  const nextPath = String(formData.get("next") ?? "/app")

  if (!email || !email.includes("@")) {
    redirect("/login?error=Enter an email before using temporary sign in.")
  }

  await setDevSession(email)
  redirect(nextPath.startsWith("/") ? nextPath : "/app")
}
