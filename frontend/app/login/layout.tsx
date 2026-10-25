import type { Metadata } from "next"
import type { ReactNode } from "react"

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to talk to the broker. Email a magic link, or continue with Google."
}

export default function LoginLayout({ children }: { children: ReactNode }) {
  return children
}
