import "./globals.css"

import { Plus_Jakarta_Sans } from "next/font/google"
import type { ReactNode } from "react"

import { ThemeSwitcher } from "@/components/theme-switcher"

const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans"
})

export const metadata = {
  title: "BrokerAI",
  description: "A private AI broker for requests, offers, matches, and deal-making."
}

const themeBootScript = `(function(){try{if(localStorage.getItem("brokerai-theme")==="poster"){document.documentElement.dataset.theme="poster"}}catch(e){}})()`
const showThemeSwitcher = process.env.NODE_ENV !== "production"

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={sans.variable} suppressHydrationWarning>
      <body className="min-h-screen bg-canvas font-sans text-ink antialiased">
        {showThemeSwitcher ? (
          <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
        ) : null}
        {children}
        {showThemeSwitcher ? <ThemeSwitcher /> : null}
      </body>
    </html>
  )
}
