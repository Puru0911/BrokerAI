"use server"

import { redirect } from "next/navigation"

import { createMyProfile, getAccessToken } from "@/lib/api/user-profile"

export type CreateProfileState = {
  error: string | null
}

export async function createProfile(
  _state: CreateProfileState,
  formData: FormData
): Promise<CreateProfileState> {
  const name = String(formData.get("name") ?? "").trim()
  const location = String(formData.get("location") ?? "").trim()
  const mobileNumber = String(formData.get("mobile_number") ?? "").trim()

  if (name.length < 2) {
    return { error: "Enter your full name." }
  }

  if (location.length < 2) {
    return { error: "Enter your city or location." }
  }

  if (mobileNumber.length < 7) {
    return { error: "Enter a valid mobile number." }
  }

  const accessToken = await getAccessToken()
  if (!accessToken) {
    redirect("/login?next=/profile")
  }

  try {
    await createMyProfile(accessToken, {
      name,
      location,
      mobile_number: mobileNumber
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
