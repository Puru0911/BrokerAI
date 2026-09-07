import "./globals.css"

import { Plus_Jakarta_Sans } from "next/font/google"
import type { ReactNode } from "react"

const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans"
})

export const metadata = {
  title: "BrokerAI",
  description: "A private AI broker for requests, offers, matches, and deal-making."
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body className="min-h-screen bg-canvas font-sans text-ink antialiased">
        {children}
      </body>
    </html>
  )
}
