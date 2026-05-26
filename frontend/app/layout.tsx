import "./globals.css"
import type { ReactNode } from "react"

export const metadata = {
  title: "BrokerAI",
  description: "An AI broker that matches people and needs"
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-zinc-900">{children}</body>
    </html>
  )
}
