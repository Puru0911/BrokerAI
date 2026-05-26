import Image from "next/image"
import { redirect } from "next/navigation"

import { BackendUnavailable } from "@/components/profile/backend-unavailable"
import { CreateProfileForm } from "@/components/profile/create-profile-form"
import { fetchMyProfile, getCurrentAuthIdentity } from "@/lib/api/user-profile"

export default async function ProfilePage() {
  const authIdentity = await getCurrentAuthIdentity()
  if (!authIdentity) {
    redirect("/login?next=/profile")
  }

  const profile = await fetchMyProfile(authIdentity.accessToken).catch((error) => {
    return error instanceof Error ? error : new Error("Profile lookup failed")
  })

  if (profile instanceof Error) {
    return <BackendUnavailable message={profile.message} />
  }

  if (profile) {
    redirect("/app")
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f6faf9] px-5 py-10">
      <section className="w-full max-w-md rounded-md border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <Image
          src="/brokerai-logo.jpg"
          alt="BrokerAI logo"
          width={96}
          height={96}
          className="mx-auto rounded-md object-cover"
          priority
        />
        <div className="mt-6 space-y-2 text-center">
          <h1 className="text-2xl font-semibold text-[#10275b]">
            Create your profile
          </h1>
          <p className="text-sm leading-6 text-slate-600">
            BrokerAI uses these details to qualify matches and follow up with
            the right context.
          </p>
        </div>

        <CreateProfileForm email={authIdentity.email ?? "your account"} />
      </section>
    </main>
  )
}
