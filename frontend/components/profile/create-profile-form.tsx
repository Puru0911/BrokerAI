"use client"

import { useActionState } from "react"

import {
  createProfile,
  type CreateProfileState
} from "@/app/profile/actions"
import { Spinner } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

const initialState: CreateProfileState = {
  error: null
}

export function CreateProfileForm({ email }: { email: string }) {
  const [state, formAction, pending] = useActionState(
    createProfile,
    initialState
  )

  return (
    <form action={formAction} className="space-y-5">
      <div className="rounded-xl bg-canvas px-3 py-2 text-sm text-muted">
        Signed in as {email}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-ink" htmlFor="name">
          Name
        </label>
        <Input id="name" name="name" autoComplete="name" required />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-ink" htmlFor="location">
          Location
        </label>
        <Input
          id="location"
          name="location"
          autoComplete="address-level2"
          placeholder="City, State"
          required
        />
      </div>

      <div className="space-y-2">
        <label
          className="text-sm font-medium text-ink"
          htmlFor="mobile_number"
        >
          Mobile number
        </label>
        <Input
          id="mobile_number"
          name="mobile_number"
          type="tel"
          autoComplete="tel"
          required
        />
      </div>

      {state.error ? (
        <div className="rounded-xl border border-danger/20 bg-danger-soft px-3 py-2 text-sm text-danger">
          {state.error}
        </div>
      ) : null}

      <Button type="submit" disabled={pending} className="h-11 w-full">
        {pending ? <Spinner className="h-4 w-4" /> : null}
        {pending ? "Saving…" : "Continue"}
      </Button>
    </form>
  )
}
