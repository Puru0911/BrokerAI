"use client"

import { AuthShell } from "@/components/layout/auth-shell"
import { Button } from "@/components/ui/button"

export function BackendUnavailable({ message }: { message: string }) {
  return (
    <AuthShell
      title="Backend connection needed"
      description={message}
    >
      <div className="rounded-xl bg-canvas px-3 py-2 text-center text-sm text-muted">
        Start FastAPI, then refresh this page.
      </div>
      <Button
        type="button"
        className="mt-5 h-11 w-full"
        onClick={() => window.location.reload()}
      >
        Refresh
      </Button>
    </AuthShell>
  )
}
