export type NotifyEmailProfile = {
  id: string
  notify_email: boolean
}

function getBackendUrl() {
  return (
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    process.env.BACKEND_URL ||
    "http://127.0.0.1:8000"
  )
}

export async function patchNotifyEmail(
  accessToken: string,
  notifyEmail: boolean
) {
  const response = await fetch(`${getBackendUrl()}/users/me`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ notify_email: notifyEmail })
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : `Could not update email settings (${response.status})`
    throw new Error(detail)
  }

  return (await response.json()) as NotifyEmailProfile
}
