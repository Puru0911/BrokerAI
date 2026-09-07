"use client"

import { FormEvent, useEffect, useMemo, useRef, useState } from "react"

import { logout } from "@/app/app/actions"
import { ChatComposer } from "@/components/chat/chat-composer"
import { ChatHeader } from "@/components/chat/chat-header"
import { MessageList } from "@/components/chat/message-list"
import { SessionSidebar } from "@/components/chat/session-sidebar"
import {
  type BrokerMessage,
  type BrokerSession,
  addBrokerLink,
  connectBrokerMatch,
  createBrokerSession,
  deleteBrokerSession,
  getBrokerSession,
  grantBrokerAttachment,
  listBrokerSessions,
  sendBrokerMessage,
  uploadBrokerAttachment
} from "@/lib/api/broker"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

type BrokerChatProps = {
  initialAccessToken: string
  userEmail: string
}

export function BrokerChat({ initialAccessToken, userEmail }: BrokerChatProps) {
  const supabase = useMemo(() => createSupabaseBrowserClient(), [])
  const messageEndRef = useRef<HTMLDivElement | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(
    initialAccessToken
  )
  const [sessions, setSessions] = useState<BrokerSession[]>([])
  const [messages, setMessages] = useState<BrokerMessage[]>([])
  const [pendingMessages, setPendingMessages] = useState<BrokerMessage[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [composerValue, setComposerValue] = useState("")
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [pendingLink, setPendingLink] = useState("")
  const [bootLoading, setBootLoading] = useState(true)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [connectingMatchId, setConnectingMatchId] = useState<string | null>(
    null
  )
  const [connectedMatchIds, setConnectedMatchIds] = useState<Set<string>>(
    new Set()
  )
  const [grantingAttachmentId, setGrantingAttachmentId] = useState<
    string | null
  >(null)
  const [uploadingRequestId, setUploadingRequestId] = useState<string | null>(
    null
  )
  const [error, setError] = useState<string | null>(null)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null
  )

  const activeSession = sessions.find(
    (session) => session.id === activeSessionId
  )
  const visibleMessages = [...messages, ...pendingMessages]
  const composerLocked = bootLoading || sessionLoading || !accessToken

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ block: "end" })
  }, [visibleMessages.length, thinking])

  useEffect(() => {
    async function bootChat() {
      setBootLoading(true)
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
            : "Could not load sessions."
        )
      } finally {
        setBootLoading(false)
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
    setCreatingSession(true)
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
      setCreatingSession(false)
    }
  }

  async function handleSelectSession(sessionId: string) {
    if (!accessToken || sessionId === activeSessionId) {
      setDrawerOpen(false)
      return
    }

    setError(null)
    setSessionLoading(true)
    setActiveSessionId(sessionId)
    setMessages([])
    setPendingMessages([])
    setDrawerOpen(false)
    try {
      const detail = await getBrokerSession(accessToken, sessionId)
      setActiveSessionId(detail.session.id)
      setMessages(detail.messages)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not open that session."
      )
    } finally {
      setSessionLoading(false)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const content = composerValue.trim()
    const files = pendingFiles
    const link = pendingLink.trim()
    if (!accessToken || (!content && files.length === 0 && !link) || thinking) {
      return
    }

    setError(null)
    setThinking(true)
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    const optimisticMessage = createLocalUserMessage(
      content ||
        (files.length
          ? `Uploaded ${files.length === 1 ? files[0].name : `${files.length} files`}`
          : link),
      activeSessionId
    )
    setPendingMessages([optimisticMessage])

    try {
      let sessionId = activeSessionId
      if (!sessionId) {
        const detail = await createBrokerSession(
          accessToken,
          files.length || link ? undefined : content
        )
        setSessions((currentSessions) => [
          detail.session,
          ...currentSessions.filter((session) => session.id !== detail.session.id)
        ])
        sessionId = detail.session.id
        setActiveSessionId(sessionId)
        if (!files.length && !link) {
          setMessages(detail.messages)
          setPendingMessages([])
          return
        }
        if (detail.messages.length) {
          setMessages(detail.messages)
        }
      }

      const attachmentIds: string[] = []
      for (const file of files) {
        const uploaded = await uploadBrokerAttachment(
          accessToken,
          sessionId,
          file,
          {
            caption: content || undefined
          }
        )
        attachmentIds.push(uploaded.id)
      }
      if (link) {
        const created = await addBrokerLink(accessToken, sessionId, link, {
          caption: content || undefined
        })
        attachmentIds.push(created.id)
      }

      if (!content && !attachmentIds.length) {
        setPendingMessages([])
        return
      }

      const newMessages = await sendBrokerMessage(
        accessToken,
        sessionId,
        content,
        attachmentIds
      )
      setMessages((currentMessages) => [...currentMessages, ...newMessages])
      setPendingMessages([])
      await refreshSessions(accessToken)
    } catch (caughtError) {
      setComposerValue(content)
      setPendingFiles(files)
      setPendingLink(link)
      setPendingMessages([])
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not send your message."
      )
    } finally {
      setThinking(false)
    }
  }

  async function handleRequestUpload(requestId: string, file: File) {
    if (!accessToken || !activeSessionId) return
    setError(null)
    setUploadingRequestId(requestId)
    try {
      const uploaded = await uploadBrokerAttachment(
        accessToken,
        activeSessionId,
        file,
        { requestId }
      )
      setUploadingRequestId(null)
      setThinking(true)
      const newMessages = await sendBrokerMessage(
        accessToken,
        activeSessionId,
        "",
        [uploaded.id]
      )
      setMessages((currentMessages) => [...currentMessages, ...newMessages])
      await refreshSessions(accessToken)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not upload that file."
      )
    } finally {
      setUploadingRequestId(null)
      setThinking(false)
    }
  }

  async function handleGrant(
    attachmentId: string,
    matchId: string,
    granted: boolean
  ) {
    if (!accessToken) return
    setError(null)
    setGrantingAttachmentId(attachmentId)
    try {
      await grantBrokerAttachment(accessToken, attachmentId, matchId, granted)
      const detail = await getBrokerSession(
        accessToken,
        activeSessionId as string
      )
      setMessages(detail.messages)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not update sharing permission."
      )
    } finally {
      setGrantingAttachmentId(null)
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!accessToken) return

    const confirmed = window.confirm(
      "Delete this session? The brief, matches, messages, and search index for it will be removed."
    )
    if (!confirmed) return

    setError(null)
    setDeletingSessionId(sessionId)
    try {
      await deleteBrokerSession(accessToken, sessionId)
      const remaining = sessions.filter((session) => session.id !== sessionId)
      setSessions(remaining)

      if (activeSessionId === sessionId) {
        if (remaining.length > 0) {
          setSessionLoading(true)
          const detail = await getBrokerSession(accessToken, remaining[0].id)
          setActiveSessionId(detail.session.id)
          setMessages(detail.messages)
          setPendingMessages([])
        } else {
          setActiveSessionId(null)
          setMessages([])
          setPendingMessages([])
        }
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not delete that session."
      )
    } finally {
      setDeletingSessionId(null)
      setSessionLoading(false)
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
    <main className="flex h-screen overflow-hidden bg-canvas text-ink">
      <SessionSidebar
        open={drawerOpen}
        userEmail={userEmail}
        sessions={sessions}
        activeSessionId={activeSessionId}
        creatingSession={creatingSession}
        deletingSessionId={deletingSessionId}
        onCreateSession={() => void handleCreateSession()}
        onSelectSession={(sessionId) => void handleSelectSession(sessionId)}
        onDeleteSession={(sessionId) => void handleDeleteSession(sessionId)}
        logoutAction={logout}
      />

      {drawerOpen ? (
        <button
          aria-label="Close sessions"
          className="fixed inset-0 z-30 bg-ink/20 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
        <ChatHeader
          title={activeSession?.title ?? "New request"}
          status={activeSession?.status ?? "intake"}
          onOpenSessions={() => setDrawerOpen(true)}
        />

        <MessageList
          messages={visibleMessages}
          bootLoading={bootLoading}
          sessionLoading={sessionLoading}
          thinking={thinking}
          error={error}
          actions={{
            connectingMatchId,
            connectedMatchIds,
            onConnect: (matchId) => void handleConnect(matchId),
            uploadingRequestId,
            onRequestUpload: (requestId, file) =>
              void handleRequestUpload(requestId, file),
            grantingAttachmentId,
            onGrant: (attachmentId, matchId, granted) =>
              void handleGrant(attachmentId, matchId, granted)
          }}
          endRef={messageEndRef}
        />

        <div className="shrink-0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-1 sm:px-6 sm:pb-5">
          <ChatComposer
            value={composerValue}
            disabled={composerLocked}
            busy={thinking}
            onChange={setComposerValue}
            onSubmit={handleSubmit}
            files={pendingFiles}
            onFilesChange={setPendingFiles}
            link={pendingLink}
            onLinkChange={setPendingLink}
          />
        </div>
      </section>
    </main>
  )
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
