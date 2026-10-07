"use server"

import { redirect } from "next/navigation"

import { createMyProfile, getAccessToken } from "@/lib/api/user-profile"

export type CreateProfileState = {
  error: string | null
}

const GENDERS = new Set(["female", "male", "other"])

export async function createProfile(
  _state: CreateProfileState,
  formData: FormData
): Promise<CreateProfileState> {
  const name = String(formData.get("name") ?? "").trim()
  const gender = String(formData.get("gender") ?? "").trim().toLowerCase()
  const dateOfBirth = String(formData.get("date_of_birth") ?? "").trim()

  if (name.length < 2) {
    return { error: "Enter the name we should use for you." }
  }

  if (!GENDERS.has(gender)) {
    return { error: "Choose how you describe your gender." }
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateOfBirth)) {
    return { error: "Enter your date of birth." }
  }

  const parsed = new Date(`${dateOfBirth}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) {
    return { error: "Enter a valid date of birth." }
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (parsed > today) {
    return { error: "Date of birth cannot be in the future." }
  }

  const oldest = new Date(today)
  oldest.setFullYear(today.getFullYear() - 120)
  if (parsed < oldest) {
    return { error: "Enter a realistic date of birth." }
  }

  const accessToken = await getAccessToken()
  if (!accessToken) {
    redirect("/login?next=/profile")
  }

  try {
    await createMyProfile(accessToken, {
      name,
      gender,
      date_of_birth: dateOfBirth
    })
  } catch (error) {
    return {
      error:
        error instanceof Error
          ? error.message
          : "Could not save your profile. Please try again."
    }
  }

  redirect("/app")
}
