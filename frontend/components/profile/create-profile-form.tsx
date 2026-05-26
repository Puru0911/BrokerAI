"use client"

import { useActionState } from "react"

import {
  createProfile,
  type CreateProfileState
} from "@/app/profile/actions"
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
    <form action={formAction} className="mt-8 space-y-5">
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
        Signed in as {email}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-700" htmlFor="name">
          Name
        </label>
        <Input id="name" name="name" autoComplete="name" required />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-700" htmlFor="location">
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
          className="text-sm font-medium text-slate-700"
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
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {state.error}
        </div>
      ) : null}

      <Button
        type="submit"
        disabled={pending}
        className="h-11 w-full bg-[#0eada6] hover:bg-[#0b9690]"
      >
        {pending ? "Saving..." : "Continue to BrokerAI"}
      </Button>
    </form>
  )
}
