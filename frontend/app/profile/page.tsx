import { redirect } from "next/navigation"

import { AuthShell } from "@/components/layout/auth-shell"
import { BackendUnavailable } from "@/components/profile/backend-unavailable"
import { CreateProfileForm } from "@/components/profile/create-profile-form"
import {
  bootstrapGoogleProfile,
  fetchMyProfile,
  getCurrentAuthIdentity,
  isGoogleIdentity
} from "@/lib/api/user-profile"

export default async function ProfilePage() {
  const authIdentity = await getCurrentAuthIdentity()
  if (!authIdentity) {
    redirect("/login?next=/profile")
  }

  const profile = await fetchMyProfile(authIdentity.accessToken).catch(
    (error) => {
      return error instanceof Error ? error : new Error("Profile lookup failed")
    }
  )

  if (profile instanceof Error) {
    return <BackendUnavailable message={profile.message} />
  }

  if (profile) {
    redirect("/app")
  }

  if (isGoogleIdentity(authIdentity)) {
    const provisioned = await bootstrapGoogleProfile(authIdentity.accessToken, {
      name: authIdentity.fullName,
      googleAccessToken: authIdentity.googleAccessToken
    })
    if (provisioned) {
      redirect("/app")
    }
  }

  return (
    <AuthShell
      title="Create your profile"
      description="We’ll use these details when we introduce you to a match."
    >
      <CreateProfileForm
        email={authIdentity.email ?? "your account"}
        defaultName={authIdentity.fullName ?? ""}
      />
    </AuthShell>
  )
}
