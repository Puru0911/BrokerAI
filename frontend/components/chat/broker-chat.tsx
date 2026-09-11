"use client"

import { FormEvent, useEffect, useMemo, useRef, useState } from "react"

import { logout } from "@/app/app/actions"
import { ChatComposer } from "@/components/chat/chat-composer"
import { ChatHeader } from "@/components/chat/chat-header"
import { ConnectionThread } from "@/components/chat/connection-thread"
import { MessageList } from "@/components/chat/message-list"
import { SessionSidebar } from "@/components/chat/session-sidebar"
import {
  type BrokerMessage,
  type BrokerSession,
  type ConnectionMessage,
  type ConnectionSummary,
  addBrokerLink,
  connectBrokerMatch,
  createBrokerSession,
  deleteBrokerSession,
  getBrokerConnection,
  getBrokerSession,
  grantBrokerAttachment,
  listBrokerConnections,
  listBrokerSessions,
  sendBrokerMessage,
  sendConnectionMessage,
  uploadBrokerAttachment,
  uploadConnectionAttachment
} from "@/lib/api/broker"
import { connectBrokerSocket } from "@/lib/chat-socket"
import { enablePushNotifications } from "@/lib/push"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

type BrokerChatProps = {
  initialAccessToken: string
  userEmail: string
}

export function BrokerChat({ initialAccessToken, userEmail }: BrokerChatProps) {
  const supabase = useMemo(() => createSupabaseBrowserClient(), [])
  const messageEndRef = useRef<HTMLDivElement | null>(null)
  const pushAttempted = useRef(false)
  const [accessToken, setAccessToken] = useState<string | null>(
    initialAccessToken
  )
  const [sessions, setSessions] = useState<BrokerSession[]>([])
  const [connections, setConnections] = useState<ConnectionSummary[]>([])
  const [messages, setMessages] = useState<BrokerMessage[]>([])
  const [pendingMessages, setPendingMessages] = useState<BrokerMessage[]>([])
  const [connectionMessages, setConnectionMessages] = useState<
    ConnectionMessage[]
  >([])
  const [pendingConnectionMessages, setPendingConnectionMessages] = useState<
    ConnectionMessage[]
  >([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(
    null
  )
  const [pendingChatId, setPendingChatId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [composerValue, setComposerValue] = useState("")
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [pendingLink, setPendingLink] = useState("")
  const [bootLoading, setBootLoading] = useState(true)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [connectionLoading, setConnectionLoading] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [sending, setSending] = useState(false)
  const [connectingMatchId, setConnectingMatchId] = useState<string | null>(
    null
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
  const activeConnection = connections.find(
    (connection) => connection.id === activeConnectionId
  )
  const visibleMessages = [...messages, ...pendingMessages]
  const visibleConnectionMessages = [
    ...connectionMessages,
    ...pendingConnectionMessages
  ]
  const connectedMatchIds = useMemo(
    () => new Set(connections.map((connection) => connection.match_id)),
    [connections]
  )
  const viewingConnection = Boolean(activeConnectionId)
  const composerLocked =
    bootLoading || sessionLoading || connectionLoading || !accessToken
  const composerBusy = viewingConnection ? sending : thinking
  const activeConnectionIdRef = useRef(activeConnectionId)
  activeConnectionIdRef.current = activeConnectionId

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ block: "end" })
  }, [
    visibleMessages.length,
    visibleConnectionMessages.length,
    thinking,
    sending
  ])

  useEffect(() => {
    const chatId = new URLSearchParams(window.location.search).get("chat")
    if (chatId) setPendingChatId(chatId)
  }, [])

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return

    function onMessage(event: MessageEvent) {
      const connectionId = event.data?.connection_id
      if (event.data?.type === "open-chat" && typeof connectionId === "string") {
        setPendingChatId(connectionId)
      }
    }

    navigator.serviceWorker.addEventListener("message", onMessage)
    return () => {
      navigator.serviceWorker.removeEventListener("message", onMessage)
    }
  }, [])

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
        const [sessionList, connectionList] = await Promise.all([
          listBrokerSessions(token),
          listBrokerConnections(token)
        ])
        setSessions(sessionList)
        setConnections(connectionList)
        if (connectionList.length) {
          void tryEnablePush(token)
        }

        const chatId = new URLSearchParams(window.location.search).get("chat")
        if (chatId && connectionList.some((item) => item.id === chatId)) {
          setActiveConnectionId(chatId)
          setConnectionLoading(true)
          setPendingChatId(chatId)
          return
        }

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

  useEffect(() => {
    if (!accessToken) return

    const socket = connectBrokerSocket(accessToken, (event) => {
      if (event.type === "connection.created") {
        upsertConnection(event.connection)
        void tryEnablePush(accessToken)
        return
      }
      if (event.type === "connection.message") {
        upsertConnection(event.connection)
        setConnectionMessages((current) => {
          if (
            event.message.connection_id !== activeConnectionIdRef.current ||
            current.some((item) => item.id === event.message.id)
          ) {
            return current
          }
          return [...current, event.message]
        })
        setPendingConnectionMessages((current) =>
          current.filter((item) => item.id !== event.message.id)
        )
        if (event.message.connection_id === activeConnectionIdRef.current) {
          socket.markRead(event.message.connection_id)
          setConnections((current) =>
            current.map((item) =>
              item.id === event.message.connection_id
                ? { ...item, unread_count: 0 }
                : item
            )
          )
        }
      }
    })

    return () => socket.close()
  }, [accessToken])

  useEffect(() => {
    if (!pendingChatId || !accessToken) return
    if (!connections.some((item) => item.id === pendingChatId)) return
    void openConnection(accessToken, pendingChatId)
    setPendingChatId(null)
  }, [pendingChatId, connections, accessToken])

  async function tryEnablePush(token: string) {
    if (pushAttempted.current) return
    pushAttempted.current = true
    try {
      await enablePushNotifications(token)
    } catch {
      pushAttempted.current = false
    }
  }

  function upsertConnection(summary: ConnectionSummary) {
    setConnections((current) => {
      const rest = current.filter((item) => item.id !== summary.id)
      const unread =
        summary.id === activeConnectionIdRef.current ? 0 : summary.unread_count
      return [{ ...summary, unread_count: unread }, ...rest]
    })
  }

  function setChatQuery(connectionId: string | null) {
    const url = new URL(window.location.href)
    if (connectionId) {
      url.searchParams.set("chat", connectionId)
    } else {
      url.searchParams.delete("chat")
    }
    window.history.replaceState(null, "", url.pathname + url.search)
  }

  async function refreshSessions(token: string) {
    const sessionList = await listBrokerSessions(token)
    setSessions(sessionList)
  }

  async function openConnection(token: string, connectionId: string) {
    setError(null)
    setConnectionLoading(true)
    setActiveConnectionId(connectionId)
    setConnectionMessages([])
    setPendingConnectionMessages([])
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setChatQuery(connectionId)
    try {
      const detail = await getBrokerConnection(token, connectionId)
      setActiveConnectionId(detail.connection.id)
      setConnectionMessages(detail.messages)
      upsertConnection({ ...detail.connection, unread_count: 0 })
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not open that chat."
      )
    } finally {
      setConnectionLoading(false)
    }
  }

  async function handleCreateSession() {
    if (!accessToken) return

    setError(null)
    setCreatingSession(true)
    try {
      const detail = await createBrokerSession(accessToken)
      setSessions((currentSessions) => [detail.session, ...currentSessions])
      setActiveSessionId(detail.session.id)
      setActiveConnectionId(null)
      setMessages(detail.messages)
      setPendingMessages([])
      setComposerValue("")
      setPendingFiles([])
      setPendingLink("")
      setDrawerOpen(false)
      setChatQuery(null)
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
    if (!accessToken) {
      setDrawerOpen(false)
      return
    }
    if (sessionId === activeSessionId && !activeConnectionId) {
      setDrawerOpen(false)
      return
    }

    setError(null)
    setSessionLoading(true)
    setActiveSessionId(sessionId)
    setActiveConnectionId(null)
    setMessages([])
    setPendingMessages([])
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setChatQuery(null)
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

  async function handleSelectConnection(connectionId: string) {
    if (!accessToken) return
    if (connectionId === activeConnectionId) {
      setDrawerOpen(false)
      return
    }
    await openConnection(accessToken, connectionId)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const content = composerValue.trim()
    const files = pendingFiles
    const link = pendingLink.trim()
    if (
      !accessToken ||
      (!content && files.length === 0 && !link) ||
      composerBusy
    ) {
      return
    }

    if (activeConnectionId) {
      await submitConnectionMessage(accessToken, activeConnectionId, content, files)
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

  async function submitConnectionMessage(
    token: string,
    connectionId: string,
    content: string,
    files: File[]
  ) {
    setError(null)
    setSending(true)
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    const optimistic = createLocalConnectionMessage(content, files, connectionId)
    setPendingConnectionMessages([optimistic])

    try {
      const attachmentIds: string[] = []
      for (const file of files) {
        const uploaded = await uploadConnectionAttachment(
          token,
          connectionId,
          file
        )
        attachmentIds.push(uploaded.id)
      }
      const saved = await sendConnectionMessage(
        token,
        connectionId,
        content,
        attachmentIds
      )
      setConnectionMessages((current) =>
        current.some((item) => item.id === saved.id)
          ? current
          : [...current, saved]
      )
      setPendingConnectionMessages([])
      setConnections((current) => {
        const existing = current.find((item) => item.id === connectionId)
        if (!existing) return current
        return [
          {
            ...existing,
            last_message: saved,
            unread_count: 0,
            updated_at: saved.created_at
          },
          ...current.filter((item) => item.id !== connectionId)
        ]
      })
    } catch (caughtError) {
      setComposerValue(content)
      setPendingFiles(files)
      setPendingConnectionMessages([])
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not send your message."
      )
    } finally {
      setSending(false)
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

      if (activeSessionId === sessionId && !activeConnectionId) {
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
      const connection = await connectBrokerMatch(accessToken, matchId)
      upsertConnection(connection)
      void tryEnablePush(accessToken)
      await openConnection(accessToken, connection.id)
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

  function handleOpenChat(matchId: string) {
    const connection = connections.find((item) => item.match_id === matchId)
    if (!connection || !accessToken) return
    void openConnection(accessToken, connection.id)
  }

  const headerTitle = viewingConnection
    ? activeConnection?.peer.name ?? "Chat"
    : (activeSession?.title ?? "New request")
  const headerStatus = viewingConnection
    ? activeConnection?.peer.request_title || "Direct chat"
    : (activeSession?.status ?? "intake")

  return (
    <main className="flex h-screen overflow-hidden bg-canvas text-ink">
      <SessionSidebar
        open={drawerOpen}
        userEmail={userEmail}
        sessions={sessions}
        connections={connections}
        activeSessionId={activeSessionId}
        activeConnectionId={activeConnectionId}
        creatingSession={creatingSession}
        deletingSessionId={deletingSessionId}
        onCreateSession={() => void handleCreateSession()}
        onSelectSession={(sessionId) => void handleSelectSession(sessionId)}
        onSelectConnection={(connectionId) =>
          void handleSelectConnection(connectionId)
        }
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
          title={headerTitle}
          status={headerStatus}
          onOpenSessions={() => setDrawerOpen(true)}
        />

        {viewingConnection ? (
          <ConnectionThread
            messages={visibleConnectionMessages}
            loading={bootLoading || connectionLoading}
            error={error}
            peerName={activeConnection?.peer.name ?? "your match"}
            endRef={messageEndRef}
          />
        ) : (
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
              onOpenChat: handleOpenChat,
              uploadingRequestId,
              onRequestUpload: (requestId, file) =>
                void handleRequestUpload(requestId, file),
              grantingAttachmentId,
              onGrant: (attachmentId, matchId, granted) =>
                void handleGrant(attachmentId, matchId, granted)
            }}
            endRef={messageEndRef}
          />
        )}

        <div className="shrink-0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-1 sm:px-6 sm:pb-5">
          <ChatComposer
            value={composerValue}
            disabled={composerLocked}
            busy={composerBusy}
            onChange={setComposerValue}
            onSubmit={handleSubmit}
            files={pendingFiles}
            onFilesChange={setPendingFiles}
            link={pendingLink}
            onLinkChange={setPendingLink}
            placeholder={
              viewingConnection
                ? `Message ${activeConnection?.peer.name ?? "them"}…`
                : "Describe what you need, or attach a file…"
            }
            showLink={!viewingConnection}
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

function createLocalConnectionMessage(
  content: string,
  files: File[],
  connectionId: string
): ConnectionMessage {
  return {
    id: `local-conn-${Date.now()}`,
    connection_id: connectionId,
    sender_user_id: "me",
    kind: "user",
    mine: true,
    content:
      content ||
      (files.length === 1 ? files[0].name : files.length ? `${files.length} files` : ""),
    created_at: new Date().toISOString(),
    attachments: []
  }
}
