import Link from "next/link"
import type { Metadata } from "next"
import type { ReactNode } from "react"

import { SiteShell } from "@/components/layout/site-chrome"
import { getPublicSession } from "@/lib/auth/public-session"
import { AGENT_NAME } from "@/lib/agent"
import { cn } from "@/lib/cn"
import {
  PRIVACY_EMAIL,
  PRIVACY_LAST_UPDATED,
  PRIVACY_LAST_UPDATED_LABEL,
  PRODUCT_NAME,
  SITE_OPERATOR,
  SITE_URL,
  SUPPORT_EMAIL
} from "@/lib/site"

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: `How ${PRODUCT_NAME} collects, uses, and shares personal data, including Google Sign-In (name, email, profile picture, gender, and date of birth).`,
  alternates: { canonical: "/privacy" }
}

const TOC = [
  { href: "#introduction", label: "Introduction" },
  { href: "#information-we-collect", label: "Information we collect" },
  { href: "#google-sign-in", label: "Google Sign-In" },
  { href: "#how-we-use", label: "How we use information" },
  { href: "#introductions", label: "Matching and introductions" },
  { href: "#storage-security", label: "Storage and security" },
  { href: "#third-parties", label: "Third-party services" },
  { href: "#sharing", label: "Data sharing" },
  { href: "#retention", label: "Retention" },
  { href: "#your-rights", label: "Your rights" },
  { href: "#cookies", label: "Cookies" },
  { href: "#transfers", label: "International transfers" },
  { href: "#children", label: "Children" },
  { href: "#changes", label: "Changes" },
  { href: "#contact", label: "Contact" }
] as const

function Section({
  id,
  title,
  children
}: {
  id: string
  title: string
  children: ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-28">
      <h2 className="text-2xl font-semibold tracking-tight text-ink">{title}</h2>
      <div className="mt-4 space-y-4 text-[15px] leading-7 text-ink/90">
        {children}
      </div>
    </section>
  )
}

function PolicyTable({
  headers,
  rows
}: {
  headers: string[]
  rows: string[][]
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-accent-soft text-accent">
          <tr>
            {headers.map((header) => (
              <th
                key={header}
                className="px-4 py-3 font-semibold tracking-tight"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className="border-t border-line align-top">
              {row.map((cell, index) => (
                <td
                  key={`${row[0]}-${index}`}
                  className={cn(
                    "px-4 py-3 leading-6",
                    index === 0 ? "font-medium text-ink" : "text-muted"
                  )}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default async function PrivacyPage() {
  const { signedIn } = await getPublicSession()

  return (
    <SiteShell signedIn={signedIn}>
      <main className="mx-auto grid max-w-6xl gap-12 px-5 py-12 sm:px-8 lg:grid-cols-[16rem_minmax(0,1fr)] lg:py-16">
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
            Legal
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
            Privacy Policy
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Last updated {PRIVACY_LAST_UPDATED_LABEL}
            <time dateTime={PRIVACY_LAST_UPDATED} className="sr-only">
              {PRIVACY_LAST_UPDATED}
            </time>
          </p>
          <nav className="mt-8 hidden lg:block">
            <ul className="space-y-2 border-l border-line pl-4 text-sm">
              {TOC.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    className="text-muted transition hover:text-ink"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>

        <article className="max-w-3xl space-y-14 break-words [&_a]:break-all">
          <Section id="introduction" title="Introduction">
            <p>
              {SITE_OPERATOR} (“we,” “our,” or “us”) operates {PRODUCT_NAME}{" "}
              (the “Service”) at{" "}
              <a className="font-medium text-accent hover:underline" href={SITE_URL}>
                {SITE_URL}
              </a>
              . This Privacy Policy explains how we collect, use, disclose, and
              safeguard your information when you visit the website, create an
              account, or use the app.
            </p>
            <p>
              {PRODUCT_NAME} is a private AI broker. You describe what you need
              in conversation. The broker looks for a compatible counterpart,
              shows you a screened brief, and introduces you only when both
              sides accept. This policy covers that Service, including when you
              sign in with Google.
            </p>
          </Section>

          <Section id="information-we-collect" title="Information we collect">
            <h3 className="text-lg font-semibold tracking-tight text-ink">
              Account information
            </h3>
            <p>
              When you create an account we collect the identity we need to run
              the Service and to introduce you later:
            </p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>Email address</strong> — from Google Sign-In or from the
                magic-link address you enter.
              </li>
              <li>
                <strong>Name</strong> — from Google account profile data, or
                from the name you type on the create-profile form after a magic
                link.
              </li>
              <li>
                <strong>Gender</strong> — from Google (when you grant that
                permission) or from the choice you make on the create-profile
                form (Woman, Man, or Other).
              </li>
              <li>
                <strong>Date of birth</strong> — from Google (when you grant
                that permission) or from the date you enter on the
                create-profile form.
              </li>
              <li>
                <strong>Email-me-when-I’m-away preference</strong> — a toggle in
                the app that defaults to on. You can turn it off at any time.
              </li>
            </ul>
            <p>
              We do <em>not</em> currently collect a password for the product
              itself (sign-in is Google or an email magic link). We do{" "}
              <em>not</em> currently collect billing information, company name,
              job title, phone number, or home address in the product UI.
              Optional phone and location columns exist in our profile store
              for later use and stay empty unless we add those fields and tell
              you.
            </p>

            <h3 className="text-lg font-semibold tracking-tight text-ink">
              User-generated content
            </h3>
            <p>We store content you create in the Service, including:</p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Messages you send to the broker, and messages the broker sends
                you.
              </li>
              <li>
                The living brief of your request (what you are looking for),
                plus titles and summaries the broker writes from that
                conversation.
              </li>
              <li>
                Your Interested / Skip choices on candidate cards, match-lane
                chat, and any 1:1 messages after both sides connect.
              </li>
              <li>
                Files and links you attach (photos, documents, URLs), plus any
                caption you type with an upload. The broker may write a short
                description of a file from the conversation and the file type
                so it can share the right item later. We do not run vision or
                OCR on file bytes today.
              </li>
            </ul>

            <h3 className="text-lg font-semibold tracking-tight text-ink">
              Usage and technical data
            </h3>
            <p>We automatically collect:</p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Application logs needed to operate and debug the Service
                (including request times, error traces, and typical web server
                data such as IP address and user agent).
              </li>
              <li>
                Session and authentication cookies so you stay signed in.
              </li>
              <li>
                If you enable browser notifications: a Web Push subscription
                (endpoint and encryption keys for that browser). Push is used
                for 1:1 connection messages when that window is not focused.
              </li>
            </ul>
            <p>
              We do not currently use a third-party product-analytics tracker
              (for example Google Analytics) on the public site or in the app.
            </p>
          </Section>

          <Section id="google-sign-in" title="Information from Google Sign-In">
            <p>
              If you choose Continue with Google, Google authenticates you and
              (with your consent) shares account data with our sign-in
              provider. We request these Google scopes:
            </p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>openid, email, profile</strong> — Google user id, email
                address, name, and profile picture URL.
              </li>
              <li>
                <strong>user.gender.read</strong> and{" "}
                <strong>user.birthday.read</strong> — gender and date of birth
                from the Google People API, used only to complete the same
                profile fields magic-link users type themselves.
              </li>
            </ul>
            <p>
              <strong>Name and email.</strong> We copy your Google display name
              and email into your {PRODUCT_NAME} profile so we can sign you in
              and later introduce you by name.
            </p>
            <p>
              <strong>Profile picture.</strong> Google’s profile scope includes
              your account photo. That URL is received by our authentication
              provider (Supabase) as part of the Google user record. The{" "}
              {PRODUCT_NAME} app currently shows initials from your name in the
              sidebar, not that photo. We do not copy the picture into our
              application profile table, and we do not show it to other users.
            </p>
            <p>
              <strong>Gender and date of birth.</strong> Standard Google Sign-In
              does not include these. We ask for them so introductions can use
              the same identity fields for every account. If Google does not
              return them (missing year, declined permission, or People API
              unavailable), we still create your profile from name and email.
              We do not invent empty form fields to replace a declined Google
              permission.
            </p>
            <p>
              We use the Google access token once at sign-in to read name,
              gender, and birthday. We do not store that Google token in our
              application profile database. We do not read your Gmail, Drive,
              Calendar, Contacts list, or other Google products. We do not post
              to Google on your behalf.
            </p>
          </Section>

          <Section id="how-we-use" title="How we use your information">
            <PolicyTable
              headers={["Purpose", "Legal basis (GDPR)"]}
              rows={[
                [
                  "Create and maintain your account, keep you signed in, and show your name in the app",
                  "Contractual necessity"
                ],
                [
                  "Run the broker: understand your request, search for a counterpart, screen fits, and mediate a private introduction",
                  "Contractual necessity"
                ],
                [
                  "Send sign-in (magic link) email and, if you leave the toggle on, activity email when the broker reaches you while you are away",
                  "Contractual necessity; you may opt out of activity email"
                ],
                [
                  "Send Web Push for 1:1 connection messages when you have granted notification permission",
                  "Consent (browser permission)"
                ],
                [
                  "Share a contact card or a file with a counterpart only after the product’s permission rules are met",
                  "Contractual necessity; your in-product action"
                ],
                [
                  "Keep logs, prevent abuse, and keep the Service reliable",
                  "Legitimate interest"
                ],
                [
                  "Respond to privacy requests and legal obligations",
                  "Legal obligation"
                ]
              ]}
            />
            <p>
              We do not use your Google data or your chats to send marketing
              newsletters. We do not sell personal information. We do not run
              ads on the Service.
            </p>
          </Section>

          <Section id="introductions" title="Matching, AI processing, and introductions">
            <p>
              To find a counterpart, the broker builds a living brief from your
              conversation and indexes a semantic representation of that brief.
              Identity details such as email, phone, and handles are redacted
              from text that would otherwise cross to the other party before
              an accepted introduction.
            </p>
            <p>
              Candidate cards on Your request show a short brief. They do not
              show the other person’s name, email, photo, gender, or date of
              birth. A match lane exists only after you tap Interested. The
              other person is not shown your private screening of them.
            </p>
            <p>
              After both of you accept an introduction, we may share a contact
              card that can include name, email, gender, and date of birth from
              the profile. The in-app card currently displays name and the
              request title; the underlying payload may still carry those
              extra fields for the broker. Files classified as personal are
              shared only after you allow it. Files classified as shareable
              (for example a resume or listing photos) can be delivered into an
              open match by the broker.
            </p>
            <p>
              Message content, briefs, and file metadata are sent to large
              language model providers so the broker can understand you and
              choose tools. File image bytes are not sent to a vision model
              today. Model providers process that content to return a reply;
              they are not a public audience.
            </p>
          </Section>

          <Section id="storage-security" title="Data storage and security">
            <p>
              Account and product data live in PostgreSQL hosted by Supabase
              (currently AWS ap-northeast-1, Tokyo). Authentication is handled
              by Supabase Auth. Uploaded files live in a private Supabase
              Storage bucket and are reached only through our API after
              authorization, using short-lived signed URLs. The web app is
              hosted on Vercel. The API runs on Fly.io in Tokyo (nrt). Vector
              index data for briefs is stored with the API.
            </p>
            <p>
              We encrypt data in transit (HTTPS / TLS). Access to production
              systems is limited to operators of the Service. We do not claim
              SOC 2 certification or a public penetration-test program at this
              time.
            </p>
            <p>
              If a breach of personal information occurs, we will notify
              affected users and, where required, supervisory authorities
              without undue delay (including within 72 hours where GDPR
              requires it), with the nature of the incident and the steps we
              are taking.
            </p>
          </Section>

          <Section id="third-parties" title="Third-party services">
            <p>
              We use the following processors. Each has its own privacy policy.
            </p>
            <PolicyTable
              headers={["Service", "Purpose", "Data shared"]}
              rows={[
                [
                  "Google",
                  "Sign-In and, if you consent, People API (name, gender, birthday). Profile photo URL is part of the basic profile scope",
                  "Google account identifiers and the scopes you grant"
                ],
                [
                  "Supabase",
                  "Authentication, application database, and private file storage",
                  "Account, profile, chats, matches, files, session cookies"
                ],
                [
                  "Vercel",
                  "Host the website and app",
                  "HTTP request data (IP, user agent, URL)"
                ],
                [
                  "Fly.io",
                  "Host the API, WebSocket, and brief index",
                  "API request data, application logs"
                ],
                [
                  "Resend",
                  "Transactional email: magic-link is sent by Supabase; activity email (broker outreach, introduction offered, contacts delivered) is sent when you are offline and have not opted out",
                  "Email address, name, and the short notice in that message"
                ],
                [
                  "OpenRouter, Groq, and/or Google Gemini (model providers)",
                  "Run the broker’s language model so it can understand requests and reply",
                  "Conversation text, briefs, and file metadata needed for that turn"
                ],
                [
                  "Browser push services (for example FCM / Mozilla / Apple)",
                  "Deliver Web Push if you enable notifications",
                  "Push endpoint and keys for that browser"
                ]
              ]}
            />
            <p>
              We do not use a payment processor. There is no subscription
              billing in the current Service.
            </p>
          </Section>

          <Section id="sharing" title="Data sharing">
            <p>We do not sell your personal information. We share data:</p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>With a counterpart you match</strong> — only under the
                introduction and file-sharing rules above, after you act in the
                product (Interested, accept introduction, allow a personal
                file).
              </li>
              <li>
                <strong>With service providers</strong> — the processors listed
                above, strictly to operate the Service.
              </li>
              <li>
                <strong>For legal compliance</strong> — when required by law,
                subpoena, or court order, or to protect the Service and its
                users.
              </li>
              <li>
                <strong>During a business transfer</strong> — in connection with
                a merger, acquisition, or asset sale. We will notify you if
                that happens.
              </li>
            </ul>
            <p>
              There are no team or organization admin plans. Nobody else gets a
              dashboard over your chats.
            </p>
          </Section>

          <Section id="retention" title="Data retention">
            <PolicyTable
              headers={["Data type", "Retention"]}
              rows={[
                [
                  "Account and profile",
                  "While your account is active, then deleted or anonymized after a deletion request, unless law requires a longer hold"
                ],
                [
                  "Chats, briefs, matches, and files",
                  "While your account is active. Deleting a request in the app closes or tombstones that session; remaining match history for the other party may be kept so their thread still makes sense"
                ],
                [
                  "Auth logs and application logs",
                  "As needed to operate and secure the Service, typically up to 12 months"
                ],
                [
                  "Push subscriptions",
                  "Until you revoke notification permission, sign out on that browser, or we remove a dead endpoint"
                ],
                [
                  "Activity email log",
                  "Enough to avoid sending the same notice twice"
                ]
              ]}
            />
            <p>
              The current product does not include a self-serve “delete my
              account” button. Email {PRIVACY_EMAIL} to request deletion of
              your account and associated data. We will remove or anonymize
              personal data we control, except where we must keep a record
              (for example a legal hold or a security log).
            </p>
          </Section>

          <Section id="your-rights" title="Your rights">
            <h3 className="text-lg font-semibold tracking-tight text-ink">
              All users
            </h3>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>Access</strong> — request a copy of the personal data we
                hold.
              </li>
              <li>
                <strong>Correction</strong> — ask us to fix inaccurate name,
                gender, or date of birth.
              </li>
              <li>
                <strong>Deletion</strong> — request deletion of your account.
              </li>
              <li>
                <strong>Export</strong> — request a machine-readable copy of
                your profile and chats.
              </li>
              <li>
                <strong>Email opt-out</strong> — turn off “Email me when I’m
                away” in the app, or use the unsubscribe link in an activity
                email.
              </li>
            </ul>
            <h3 className="text-lg font-semibold tracking-tight text-ink">
              GDPR (EEA/UK residents)
            </h3>
            <p>
              You may also have the right to restrict processing, to data
              portability, to withdraw consent (for example notification
              permission or Google scopes by disconnecting Google), and to
              lodge a complaint with a supervisory authority. We have not
              appointed a separate Data Protection Officer; contact{" "}
              {PRIVACY_EMAIL}.
            </p>
            <h3 className="text-lg font-semibold tracking-tight text-ink">
              CCPA (California residents)
            </h3>
            <p>
              You have the right to know what personal information is
              collected, to request deletion, to opt out of the sale of
              personal information (we do not sell data), and to
              non-discrimination for exercising those rights.
            </p>
            <p>
              To exercise any of these rights, email{" "}
              <a
                className="font-medium text-accent hover:underline"
                href={`mailto:${PRIVACY_EMAIL}`}
              >
                {PRIVACY_EMAIL}
              </a>
              .
            </p>
          </Section>

          <Section id="cookies" title="Cookies">
            <p>We use cookies and similar storage for:</p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>Authentication</strong> — Supabase session cookies so
                you stay signed in. These are required for the app to work.
              </li>
              <li>
                <strong>Security</strong> — to complete the sign-in code
                exchange (PKCE) in the same browser that started login.
              </li>
            </ul>
            <p>
              We do not use advertising cookies. You can clear cookies in your
              browser; doing so will sign you out.
            </p>
          </Section>

          <Section id="transfers" title="International data transfers">
            <p>
              If you use the Service from outside Japan, your data is
              transferred to and processed in Japan (Supabase Tokyo, Fly.io
              Tokyo) and in the countries of our other processors, including
              the United States (Google, Vercel, Resend, and model providers).
              Where required, we rely on appropriate safeguards such as the
              processors’ Standard Contractual Clauses and their data
              processing terms.
            </p>
          </Section>

          <Section id="children" title="Children’s privacy">
            <p>
              The Service is for adults. It is not intended for anyone under
              18. We do not knowingly collect personal information from
              children. Because we store date of birth for introductions, do
              not use {PRODUCT_NAME} if you are under 18. If you believe we
              have collected data from a minor, email {PRIVACY_EMAIL} and we
              will delete it.
            </p>
          </Section>

          <Section id="changes" title="Changes to this policy">
            <p>
              We will post updates on this page and change the “Last updated”
              date. For material changes we will also notify you by email or
              in the app when we can. Continued use of the Service after an
              update means you accept the revised policy.
            </p>
          </Section>

          <Section id="contact" title="Contact">
            <p>
              For privacy questions, access or deletion requests, or Google
              Sign-In data:
            </p>
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Privacy:{" "}
                <a
                  className="font-medium text-accent hover:underline"
                  href={`mailto:${PRIVACY_EMAIL}`}
                >
                  {PRIVACY_EMAIL}
                </a>
              </li>
              <li>
                General:{" "}
                <a
                  className="font-medium text-accent hover:underline"
                  href={`mailto:${SUPPORT_EMAIL}`}
                >
                  {SUPPORT_EMAIL}
                </a>
              </li>
              <li>
                Operator: {SITE_OPERATOR}, website{" "}
                <a className="font-medium text-accent hover:underline" href={SITE_URL}>
                  {SITE_URL}
                </a>
              </li>
            </ul>
            <p>Email is the contact method for this policy.</p>
            <p className="text-sm text-muted">
              Structure adapted from the{" "}
              <a
                className="text-accent hover:underline"
                href="https://github.com/ryuno2525/privacy-policy-templates/blob/main/templates/saas-web-app.md"
              >
                SaaS / web app privacy template
              </a>{" "}
              (PolicyForge / ryuno2525), rewritten to match what {PRODUCT_NAME}{" "}
              actually collects and does.
            </p>
            <p>
              <Link href="/" className="font-medium text-accent hover:underline">
                Back to home
              </Link>
            </p>
          </Section>
        </article>
      </main>
    </SiteShell>
  )
}
