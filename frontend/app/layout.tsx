import "./globals.css"

import { Plus_Jakarta_Sans } from "next/font/google"
import type { Metadata } from "next"
import type { ReactNode } from "react"

import { ThemeSwitcher } from "@/components/theme-switcher"
import { AGENT_NAME } from "@/lib/agent"
import { SITE_DESCRIPTION, SITE_URL } from "@/lib/site"

const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans"
})

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: AGENT_NAME,
    template: `%s · ${AGENT_NAME}`
  },
  description: SITE_DESCRIPTION,
  applicationName: AGENT_NAME,
  openGraph: {
    type: "website",
    siteName: AGENT_NAME,
    title: AGENT_NAME,
    description: SITE_DESCRIPTION,
    url: SITE_URL
  }
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
