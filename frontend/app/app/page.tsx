import { redirect } from "next/navigation"

import { BrokerChat } from "@/components/chat/broker-chat"
import { BackendUnavailable } from "@/components/profile/backend-unavailable"
import { fetchMyProfile, getCurrentAuthIdentity } from "@/lib/api/user-profile"

export default async function AppHomePage() {
  const authIdentity = await getCurrentAuthIdentity()
  if (!authIdentity) {
    redirect("/login?next=/app")
  }

  const profile = await fetchMyProfile(authIdentity.accessToken).catch((error) => {
    return error instanceof Error ? error : new Error("Profile lookup failed")
  })

  if (profile instanceof Error) {
    return <BackendUnavailable message={profile.message} />
  }

  if (!profile) {
    redirect("/profile")
  }

  return (
    <BrokerChat
      initialAccessToken={authIdentity.accessToken}
      userEmail={authIdentity.email ?? profile.email ?? "Signed in"}
    />
  )
}
