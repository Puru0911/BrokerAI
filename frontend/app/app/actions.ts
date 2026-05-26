"use server"

import { redirect } from "next/navigation"

import { clearDevSession } from "@/lib/auth/dev-session"
import { createSupabaseServerClient } from "@/lib/supabase/server"

export async function logout() {
  const supabase = await createSupabaseServerClient()
  await supabase.auth.signOut()
  await clearDevSession()
  redirect("/login")
}
