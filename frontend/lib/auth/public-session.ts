import { getCurrentAuthIdentity } from "@/lib/api/user-profile"

export async function getPublicSession(): Promise<{ signedIn: boolean }> {
  try {
    const identity = await getCurrentAuthIdentity()
    return { signedIn: Boolean(identity) }
  } catch {
    return { signedIn: false }
  }
}
