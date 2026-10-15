import { AuthShell } from "@/components/layout/auth-shell"

function backendUrl() {
  return (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "http://127.0.0.1:8000"
  )
}

async function unsubscribe(token: string) {
  if (!token) {
    return {
      ok: false,
      title: "Link expired",
      message:
        "This unsubscribe link is invalid or has expired. Open the app to change email settings."
    }
  }

  try {
    const response = await fetch(
      `${backendUrl()}/mail/unsubscribe?token=${encodeURIComponent(token)}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(8000)
      }
    )
    const body = (await response.json().catch(() => null)) as
      | { ok?: boolean; title?: string; message?: string }
      | null
    if (body?.title && body?.message) {
      return {
        ok: Boolean(body.ok),
        title: body.title,
        message: body.message
      }
    }
  } catch {
    return {
      ok: false,
      title: "Could not update email settings",
      message: "Try again in a moment, or open the app to turn off activity email."
    }
  }

  return {
    ok: false,
    title: "Could not update email settings",
    message: "Try again in a moment, or open the app to turn off activity email."
  }
}

export default async function UnsubscribePage({
  searchParams
}: {
  searchParams: Promise<{ token?: string }>
}) {
  const params = await searchParams
  const result = await unsubscribe(params.token ?? "")

  return (
    <AuthShell title={result.title} description={result.message}>
      <a
        href="/app"
        className="flex h-11 items-center justify-center rounded-xl bg-accent text-sm font-semibold text-surface transition hover:bg-accent-hover"
      >
        Back to chat
      </a>
    </AuthShell>
  )
}
