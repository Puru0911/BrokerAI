"use client"

import { useActionState, useMemo, useState } from "react"

import {
  createProfile,
  type CreateProfileState
} from "@/app/profile/actions"
import { Spinner } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/cn"

const initialState: CreateProfileState = {
  error: null
}

const GENDER_OPTIONS = [
  { value: "female", label: "Woman" },
  { value: "male", label: "Man" },
  { value: "other", label: "Other" }
] as const

function maxBirthDate() {
  const today = new Date()
  const month = String(today.getMonth() + 1).padStart(2, "0")
  const day = String(today.getDate()).padStart(2, "0")
  return `${today.getFullYear()}-${month}-${day}`
}

export function CreateProfileForm({
  email,
  defaultName = ""
}: {
  email: string
  defaultName?: string
}) {
  const [state, formAction, pending] = useActionState(
    createProfile,
    initialState
  )
  const [gender, setGender] = useState("")
  const latestBirthDate = useMemo(() => maxBirthDate(), [])

  return (
    <form action={formAction} className="space-y-6">
      <div className="rounded-2xl border border-line bg-canvas/70 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          Signed in
        </div>
        <div className="mt-1 truncate text-sm font-medium text-ink">{email}</div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-ink" htmlFor="name">
          Name
        </label>
        <Input
          id="name"
          name="name"
          autoComplete="name"
          autoCapitalize="words"
          autoFocus
          defaultValue={defaultName}
          placeholder="How should we introduce you?"
          required
        />
        <p className="text-xs leading-5 text-muted">
          This is the name the other person sees when a match is ready.
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-ink">Gender</legend>
        <input type="hidden" name="gender" value={gender} />
        <div className="grid grid-cols-3 gap-2">
          {GENDER_OPTIONS.map((option) => {
            const selected = gender === option.value
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => setGender(option.value)}
                aria-pressed={selected}
                className={cn(
                  "h-11 rounded-xl border text-sm font-medium transition",
                  selected
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-line bg-surface text-ink hover:bg-black/[0.03]"
                )}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <div className="space-y-2">
        <label className="text-sm font-medium text-ink" htmlFor="date_of_birth">
          Date of birth
        </label>
        <Input
          id="date_of_birth"
          name="date_of_birth"
          type="date"
          autoComplete="bday"
          required
          max={latestBirthDate}
          min="1905-01-01"
          className="[color-scheme:light]"
        />
      </div>

      {state.error ? (
        <div className="rounded-xl border border-danger/20 bg-danger-soft px-3 py-2 text-sm text-danger">
          {state.error}
        </div>
      ) : null}

      <Button type="submit" disabled={pending || !gender} className="h-11 w-full">
        {pending ? <Spinner className="h-4 w-4" /> : null}
        {pending ? "Saving…" : "Continue"}
      </Button>
    </form>
  )
}
