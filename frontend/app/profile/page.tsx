import { redirect } from "next/navigation"

import { AuthShell } from "@/components/layout/auth-shell"
import { BackendUnavailable } from "@/components/profile/backend-unavailable"
import { CreateProfileForm } from "@/components/profile/create-profile-form"
import { fetchMyProfile, getCurrentAuthIdentity } from "@/lib/api/user-profile"

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

  return (
    <AuthShell
      title="Create your profile"
      description="These details help qualify matches and follow up with the right context."
    >
      <CreateProfileForm email={authIdentity.email ?? "your account"} />
    </AuthShell>
  )
}
