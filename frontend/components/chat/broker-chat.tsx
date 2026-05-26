"use client"

import { FormEvent, useEffect, useMemo, useRef, useState } from "react"
import Image from "next/image"

import { logout } from "@/app/app/actions"
import { Button } from "@/components/ui/button"
import {
  type BrokerMessage,
  type BrokerSession,
  connectBrokerMatch,
  createBrokerSession,
  getBrokerSession,
  listBrokerSessions,
  sendBrokerMessage
} from "@/lib/api/broker"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

type BrokerChatProps = {
  initialAccessToken: string
  userEmail: string
}

type ContactCardPayload = {
  kind: "broker_contact_card"
  version: 1
  match_id: string
  title: string
  contact: {
    name: string
    email: string | null
    mobile_number: string
    location: string
  }
  request: {
    title: string
    summary: string
    category: string | null
    request_type: string
  }
}

const WELCOME_MESSAGE =
  "Tell me what you are looking for, offering, or trying to work out. I will help shape it into a clear request and take it from there."

export function BrokerChat({ initialAccessToken, userEmail }: BrokerChatProps) {
  const supabase = useMemo(() => createSupabaseBrowserClient(), [])
  const messageEndRef = useRef<HTMLDivElement | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(initialAccessToken)
  const [sessions, setSessions] = useState<BrokerSession[]>([])
  const [messages, setMessages] = useState<BrokerMessage[]>([])
  const [pendingMessages, setPendingMessages] = useState<BrokerMessage[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [composerValue, setComposerValue] = useState("")
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [connectingMatchId, setConnectingMatchId] = useState<string | null>(null)
  const [connectedMatchIds, setConnectedMatchIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  const activeSession = sessions.find((session) => session.id === activeSessionId)
  const visibleMessages =
    messages.length > 0
      ? [...messages, ...pendingMessages]
      : [createLocalAssistantMessage(WELCOME_MESSAGE), ...pendingMessages]

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ block: "end" })
  }, [visibleMessages.length, sending])

  useEffect(() => {
    async function bootChat() {
      setLoading(true)
      setError(null)

      try {
        const {
          data: { session }
        } = await supabase.auth.getSession()

        const token = session?.access_token ?? initialAccessToken

        if (!token) {
          setError("Your login session expired. Please sign in again.")
          return
        }

        setAccessToken(token)
        const sessionList = await listBrokerSessions(token)
        setSessions(sessionList)

        if (sessionList.length > 0) {
          const detail = await getBrokerSession(token, sessionList[0].id)
          setActiveSessionId(detail.session.id)
          setMessages(detail.messages)
          setPendingMessages([])
        } else {
          setActiveSessionId(null)
          setMessages([])
          setPendingMessages([])
        }
      } catch (caughtError) {
        setError(
          caughtError instanceof Error
            ? caughtError.message
            : "Could not load BrokerAI sessions."
        )
      } finally {
        setLoading(false)
      }
    }

    void bootChat()
  }, [initialAccessToken, supabase])

  async function refreshSessions(token: string) {
    const sessionList = await listBrokerSessions(token)
    setSessions(sessionList)
  }

  async function handleCreateSession() {
    if (!accessToken) return

    setError(null)
    setSending(true)
    try {
      const detail = await createBrokerSession(accessToken)
      setSessions((currentSessions) => [detail.session, ...currentSessions])
      setActiveSessionId(detail.session.id)
      setMessages(detail.messages)
      setPendingMessages([])
      setDrawerOpen(false)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not create a new session."
      )
    } finally {
      setSending(false)
    }
  }

  async function handleSelectSession(sessionId: string) {
    if (!accessToken) return

    setError(null)
    setLoading(true)
    try {
      const detail = await getBrokerSession(accessToken, sessionId)
      setActiveSessionId(detail.session.id)
      setMessages(detail.messages)
      setPendingMessages([])
      setDrawerOpen(false)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not open that session."
      )
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const content = composerValue.trim()
    if (!accessToken || !content) return

    setError(null)
    setSending(true)
    setComposerValue("")
    const optimisticMessage = createLocalUserMessage(content, activeSessionId)
    setPendingMessages([optimisticMessage])

    try {
      if (!activeSessionId) {
        const detail = await createBrokerSession(accessToken, content)
        setSessions((currentSessions) => [
          detail.session,
          ...currentSessions.filter((session) => session.id !== detail.session.id)
        ])
        setActiveSessionId(detail.session.id)
        setMessages(detail.messages)
        setPendingMessages([])
      } else {
        const newMessages = await sendBrokerMessage(
          accessToken,
          activeSessionId,
          content
        )
        setMessages((currentMessages) => [...currentMessages, ...newMessages])
        setPendingMessages([])
        await refreshSessions(accessToken)
      }
    } catch (caughtError) {
      setComposerValue(content)
      setPendingMessages([])
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not send your message."
      )
    } finally {
      setSending(false)
    }
  }

  async function handleConnect(matchId: string) {
    if (!accessToken) return

    setError(null)
    setConnectingMatchId(matchId)
    try {
      await connectBrokerMatch(accessToken, matchId)
      setConnectedMatchIds((currentIds) => {
        const nextIds = new Set(currentIds)
        nextIds.add(matchId)
        return nextIds
      })
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not create the connection."
      )
    } finally {
      setConnectingMatchId(null)
    }
  }

  return (
    <main className="flex h-screen overflow-hidden bg-[#f7faf9] text-slate-950">
      <aside
        className={[
          "fixed inset-y-0 left-0 z-40 flex w-80 max-w-[86vw] flex-col border-r border-slate-200 bg-white transition-transform duration-200 lg:static lg:h-screen lg:translate-x-0",
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        ].join(" ")}
      >
        <div className="flex h-20 items-center gap-3 border-b border-slate-200 px-5">
          <Image
            src="/brokerai-logo.jpg"
            alt="BrokerAI"
            width={48}
            height={48}
            className="h-12 w-12 rounded-md object-cover"
            priority
          />
          <div className="min-w-0">
            <div className="text-base font-semibold text-[#10275b]">BrokerAI</div>
            <div className="truncate text-xs text-slate-500">{userEmail}</div>
          </div>
        </div>

        <div className="border-b border-slate-200 p-4">
          <button
            onClick={handleCreateSession}
            disabled={sending || !accessToken}
            className="w-full rounded-md bg-[#0eada6] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#0b9690] disabled:opacity-50"
          >
            New session
          </button>
        </div>

        <nav className="flex-1 space-y-2 overflow-y-auto p-3" aria-label="Chat sessions">
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId

            return (
              <button
                key={session.id}
                onClick={() => void handleSelectSession(session.id)}
                className={[
                  "w-full rounded-md border px-3 py-3 text-left transition",
                  isActive
                    ? "border-[#0eada6] bg-[#e8fbf9]"
                    : "border-transparent hover:border-slate-200 hover:bg-slate-50"
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-medium">{session.title}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {formatSessionTime(session.updated_at)}
                  </span>
                </div>
                <div className="mt-1 line-clamp-1 text-xs text-slate-500">
                  {session.summary || "No request details yet"}
                </div>
                <div className="mt-2 text-xs font-medium text-[#10275b]">
                  {formatStatus(session.status)}
                </div>
              </button>
            )
          })}
        </nav>

        <form action={logout} className="border-t border-slate-200 p-4">
          <Button type="submit" variant="secondary" className="w-full">
            Sign out
          </Button>
        </form>
      </aside>

      {drawerOpen ? (
        <button
          aria-label="Close sessions"
          className="fixed inset-0 z-30 bg-slate-950/30 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-20 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              aria-label="Open sessions"
              onClick={() => setDrawerOpen(true)}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium lg:hidden"
            >
              Sessions
            </button>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold sm:text-xl">
                {activeSession?.title ?? "BrokerAI intake"}
              </h1>
              <p className="truncate text-sm text-slate-500">
                Matching workspace - {formatStatus(activeSession?.status ?? "intake")}
              </p>
            </div>
          </div>
          <div className="hidden rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-600 sm:block">
            Private broker mode
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            {loading ? (
              <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                Loading BrokerAI...
              </div>
            ) : null}

            {visibleMessages.map((message) => {
              const isUser = message.role === "user"
              const contactCard = parseContactCard(message.content)

              return (
                <div
                  key={message.id}
                  className={["flex", isUser ? "justify-end" : "justify-start"].join(
                    " "
                  )}
                >
                  <div
                    className={[
                      "max-w-[82%] rounded-md px-4 py-3 text-sm leading-6 shadow-sm",
                      isUser
                        ? "bg-[#10275b] text-white"
                        : "border border-slate-200 bg-white text-slate-800"
                    ].join(" ")}
                  >
                    {contactCard && !isUser ? (
                      <ContactCard
                        payload={contactCard}
                        connecting={connectingMatchId === contactCard.match_id}
                        connected={connectedMatchIds.has(contactCard.match_id)}
                        onConnect={() => void handleConnect(contactCard.match_id)}
                      />
                    ) : (
                      message.content
                    )}
                  </div>
                </div>
              )
            })}

            {sending ? <TypingIndicator /> : null}
            <div ref={messageEndRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-4 sm:px-6">
          <form className="mx-auto flex max-w-3xl gap-3" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="message">
              Message BrokerAI
            </label>
            <input
              id="message"
              value={composerValue}
              onChange={(event) => setComposerValue(event.target.value)}
              disabled={loading || sending || !accessToken}
              className="min-h-11 flex-1 rounded-md border border-slate-200 px-4 text-sm outline-none transition focus:border-[#0eada6] focus:ring-2 focus:ring-[#bff2ee] disabled:bg-slate-50"
              placeholder="Describe what you need or who you want to reach..."
            />
            <button
              type="submit"
              disabled={loading || sending || !composerValue.trim() || !accessToken}
              className="rounded-md bg-[#0eada6] px-5 text-sm font-semibold text-white transition hover:bg-[#0b9690] disabled:opacity-50"
            >
              {sending ? "Sending" : "Send"}
            </button>
          </form>
        </div>
      </section>
    </main>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
        BrokerAI is thinking...
      </div>
    </div>
  )
}

function createLocalAssistantMessage(content: string): BrokerMessage {
  return {
    id: "local-welcome",
    session_id: "local",
    role: "assistant",
    content,
    created_at: new Date(0).toISOString()
  }
}

function createLocalUserMessage(
  content: string,
  sessionId: string | null
): BrokerMessage {
  return {
    id: `local-user-${Date.now()}`,
    session_id: sessionId ?? "local",
    role: "user",
    content,
    created_at: new Date().toISOString()
  }
}

function ContactCard({
  payload,
  connecting,
  connected,
  onConnect
}: {
  payload: ContactCardPayload
  connecting: boolean
  connected: boolean
  onConnect: () => void
}) {
  return (
    <div className="w-full min-w-64 space-y-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-[#0eada6]">
          BrokerAI contact
        </div>
        <div className="mt-1 text-base font-semibold text-slate-950">
          {payload.contact.name}
        </div>
        <div className="text-xs text-slate-500">{payload.request.title}</div>
      </div>

      <div className="grid gap-2 text-sm">
        <div className="rounded-md bg-slate-50 px-3 py-2">
          <div className="text-xs font-medium text-slate-500">Mobile</div>
          <div className="font-medium text-slate-900">{payload.contact.mobile_number}</div>
        </div>
        {payload.contact.email ? (
          <div className="rounded-md bg-slate-50 px-3 py-2">
            <div className="text-xs font-medium text-slate-500">Email</div>
            <div className="break-all font-medium text-slate-900">
              {payload.contact.email}
            </div>
          </div>
        ) : null}
        <div className="rounded-md bg-slate-50 px-3 py-2">
          <div className="text-xs font-medium text-slate-500">Location</div>
          <div className="font-medium text-slate-900">{payload.contact.location}</div>
        </div>
      </div>

      <p className="text-xs leading-5 text-slate-500">{payload.request.summary}</p>

      <button
        type="button"
        disabled={connecting || connected}
        onClick={onConnect}
        className="w-full rounded-md bg-[#10275b] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#193875] disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {connected ? "Connection created" : connecting ? "Connecting..." : "Connect"}
      </button>
    </div>
  )
}

function parseContactCard(content: string): ContactCardPayload | null {
  try {
    const payload = JSON.parse(content) as Partial<ContactCardPayload>
    if (
      payload.kind === "broker_contact_card" &&
      payload.version === 1 &&
      typeof payload.match_id === "string" &&
      payload.contact &&
      payload.request
    ) {
      return payload as ContactCardPayload
    }
  } catch {
    return null
  }
  return null
}

function formatStatus(status: string) {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function formatSessionTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value))
}
