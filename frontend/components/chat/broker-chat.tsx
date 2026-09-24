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
import {
  filesToConnectionAttachments,
  filesToLocalAttachments,
  hydrateMessagesWithAttachments,
  localAttachmentsForSend,
  mergeIncomingAttachments,
  sortChatMessages
} from "@/lib/local-attachments"
import {
  enablePushNotifications,
  notificationPermission,
  pushSupported,
  requestNotificationPermission
} from "@/lib/push"
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
  const [thinkingSessionId, setThinkingSessionId] = useState<string | null>(
    null
  )
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
  const [showNotifyPrompt, setShowNotifyPrompt] = useState(false)
  const [notifyBusy, setNotifyBusy] = useState(false)

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
  const thinking =
    Boolean(thinkingSessionId) &&
    thinkingSessionId === activeSessionId &&
    !viewingConnection
  const composerLocked =
    bootLoading || sessionLoading || connectionLoading || !accessToken
  const composerBusy = viewingConnection
    ? sending
    : thinkingSessionId === activeSessionId
  const activeSessionIdRef = useRef(activeSessionId)
  activeSessionIdRef.current = activeSessionId
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
        if (pushSupported()) {
          void navigator.serviceWorker.register("/sw.js")
        }
        const permission = notificationPermission()
        if (permission === "granted") {
          void subscribePush(token)
        } else if (permission === "default") {
          setShowNotifyPrompt(true)
        }

        const chatId = new URLSearchParams(window.location.search).get("chat")
        if (chatId && connectionList.some((item) => item.id === chatId)) {
          setActiveConnectionId(chatId)
          setConnectionLoading(true)
          setPendingChatId(chatId)
          return
        }

        if (sessionList.length > 0) {
          const sessionId = sessionList[0].id
          const detail = await getBrokerSession(token, sessionId)
          if (activeSessionIdRef.current && activeSessionIdRef.current !== sessionId) {
            return
          }
          setActiveSessionId(detail.session.id)
          setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
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
        if (notificationPermission() === "granted") {
          void subscribePush(accessToken)
        } else if (notificationPermission() === "default") {
          setShowNotifyPrompt(true)
        }
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
          return sortChatMessages([...current, event.message])
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
    if (!accessToken || !activeSessionId || viewingConnection) return
    const sessionId = activeSessionId
    let cancelled = false
    const timer = window.setInterval(() => {
      if (thinkingSessionId === sessionId) return
      void getBrokerSession(accessToken, sessionId)
        .then((detail) => {
          if (cancelled) return
          if (activeSessionIdRef.current !== sessionId) return
          if (activeConnectionIdRef.current) return
          if (detail.session.id !== sessionId) return
          setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
        })
        .catch(() => undefined)
    }, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessToken, activeSessionId, viewingConnection, thinkingSessionId])

  useEffect(() => {
    if (!pendingChatId || !accessToken) return
    if (!connections.some((item) => item.id === pendingChatId)) return
    void openConnection(accessToken, pendingChatId)
    setPendingChatId(null)
  }, [pendingChatId, connections, accessToken])

  async function subscribePush(token: string) {
    if (pushAttempted.current) return
    pushAttempted.current = true
    try {
      const ok = await enablePushNotifications(token)
      if (ok) setShowNotifyPrompt(false)
      else pushAttempted.current = false
    } catch {
      pushAttempted.current = false
    }
  }

  async function handleEnableNotifications() {
    if (!accessToken) return
    setNotifyBusy(true)
    try {
      const permission = await requestNotificationPermission()
      if (permission === "granted") {
        pushAttempted.current = false
        await subscribePush(accessToken)
        setShowNotifyPrompt(false)
      } else {
        setShowNotifyPrompt(false)
      }
    } finally {
      setNotifyBusy(false)
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
    activeConnectionIdRef.current = connectionId
    setConnectionMessages([])
    setPendingConnectionMessages([])
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setChatQuery(connectionId)
    try {
      const detail = await getBrokerConnection(token, connectionId)
      if (activeConnectionIdRef.current !== connectionId) return
      setActiveConnectionId(detail.connection.id)
      setConnectionMessages(sortChatMessages(detail.messages))
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
      activeSessionIdRef.current = detail.session.id
      setActiveConnectionId(null)
      setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
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
    activeSessionIdRef.current = sessionId
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
      if (activeSessionIdRef.current !== sessionId) return
      setActiveSessionId(detail.session.id)
      setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
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
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    const localAttachments = localAttachmentsForSend({
      files,
      link,
      content,
      sessionId: activeSessionId
    })
    const optimisticMessage = createLocalUserMessage(
      content,
      activeSessionId,
      localAttachments
    )
    setPendingMessages([optimisticMessage])
    let sessionId = activeSessionId

    try {
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
        activeSessionIdRef.current = sessionId
        if (!files.length && !link) {
          if (activeSessionIdRef.current === sessionId) {
            setMessages(
              hydrateMessagesWithAttachments(detail.messages, detail.attachments)
            )
            setPendingMessages([])
          }
          return
        }
        if (detail.messages.length && activeSessionIdRef.current === sessionId) {
          setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
        }
      }
      setThinkingSessionId(sessionId)

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
      if (activeSessionIdRef.current === sessionId) {
        setMessages((currentMessages) => {
          const seen = new Set(currentMessages.map((message) => message.id))
          return sortChatMessages([
            ...currentMessages,
            ...newMessages
              .filter((message) => !seen.has(message.id))
              .map((message) => ({
                ...message,
                attachments: mergeIncomingAttachments(message, localAttachments)
              }))
          ])
        })
        setPendingMessages([])
      }
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
      setThinkingSessionId((current) =>
        current === sessionId ? null : current
      )
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
    const localAttachments = filesToConnectionAttachments(files, connectionId)
    const optimistic = createLocalConnectionMessage(
      content,
      files,
      connectionId,
      localAttachments
    )
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
      const savedWithAttachments = {
        ...saved,
        attachments:
          saved.attachments?.length > 0 ? saved.attachments : localAttachments
      }
      if (activeConnectionIdRef.current === connectionId) {
        setConnectionMessages((current) =>
          current.some((item) => item.id === savedWithAttachments.id)
            ? current
            : sortChatMessages([...current, savedWithAttachments])
        )
        setPendingConnectionMessages([])
      }
      setConnections((current) => {
        const existing = current.find((item) => item.id === connectionId)
        if (!existing) return current
        return [
          {
            ...existing,
            last_message: savedWithAttachments,
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
    const sessionId = activeSessionId
    setError(null)
    setUploadingRequestId(requestId)
    const localAttachments = filesToLocalAttachments([file], sessionId)
    try {
      const uploaded = await uploadBrokerAttachment(
        accessToken,
        sessionId,
        file,
        { requestId }
      )
      setUploadingRequestId(null)
      setThinkingSessionId(sessionId)
      setPendingMessages([
        createLocalUserMessage("", sessionId, localAttachments)
      ])
      const newMessages = await sendBrokerMessage(
        accessToken,
        sessionId,
        "",
        [uploaded.id]
      )
      if (activeSessionIdRef.current === sessionId) {
        setMessages((currentMessages) => {
          const seen = new Set(currentMessages.map((message) => message.id))
          return sortChatMessages([
            ...currentMessages,
            ...newMessages
              .filter((message) => !seen.has(message.id))
              .map((message) => ({
                ...message,
                attachments: mergeIncomingAttachments(message, localAttachments)
              }))
          ])
        })
        setPendingMessages([])
      }
      await refreshSessions(accessToken)
    } catch (caughtError) {
      setPendingMessages([])
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not upload that file."
      )
    } finally {
      setUploadingRequestId(null)
      setThinkingSessionId((current) =>
        current === sessionId ? null : current
      )
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
    const sessionId = activeSessionId
    try {
      await grantBrokerAttachment(accessToken, attachmentId, matchId, granted)
      if (!sessionId) return
      const detail = await getBrokerSession(accessToken, sessionId)
      if (activeSessionIdRef.current !== sessionId) return
      setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
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

      if (activeSessionIdRef.current === sessionId && !activeConnectionIdRef.current) {
        if (remaining.length > 0) {
          setSessionLoading(true)
          const nextId = remaining[0].id
          const detail = await getBrokerSession(accessToken, nextId)
          if (activeSessionIdRef.current !== sessionId) return
          setActiveSessionId(detail.session.id)
          activeSessionIdRef.current = detail.session.id
          setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
          setPendingMessages([])
        } else {
          setActiveSessionId(null)
          activeSessionIdRef.current = null
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
    const permissionPromise = pushSupported()
      ? requestNotificationPermission()
      : Promise.resolve("unsupported" as const)
    try {
      const connection = await connectBrokerMatch(accessToken, matchId)
      upsertConnection(connection)
      const permission = await permissionPromise
      if (permission === "granted") {
        pushAttempted.current = false
        void subscribePush(accessToken)
      } else if (permission === "default") {
        setShowNotifyPrompt(true)
      }
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

        {showNotifyPrompt ? (
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-accent-soft px-4 py-2.5 sm:px-6">
            <p className="min-w-0 text-sm text-ink">
              Turn on notifications so you don’t miss a new chat.
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => void handleEnableNotifications()}
                disabled={notifyBusy}
                className="h-8 rounded-lg bg-accent px-3 text-xs font-semibold text-surface transition hover:bg-[#0c4d48] disabled:opacity-50"
              >
                {notifyBusy ? "Enabling…" : "Enable"}
              </button>
              <button
                type="button"
                onClick={() => setShowNotifyPrompt(false)}
                className="h-8 rounded-lg px-2 text-xs font-medium text-muted transition hover:text-ink"
              >
                Not now
              </button>
            </div>
          </div>
        ) : null}

        {viewingConnection ? (
          <ConnectionThread
            messages={visibleConnectionMessages}
            loading={bootLoading || connectionLoading}
            error={error}
            peerName={activeConnection?.peer.name ?? "your match"}
            accessToken={accessToken}
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
              accessToken,
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
  sessionId: string | null,
  attachments: BrokerMessage["attachments"] = []
): BrokerMessage {
  return {
    id: `local-user-${Date.now()}`,
    session_id: sessionId ?? "local",
    role: "user",
    content,
    created_at: new Date().toISOString(),
    attachments
  }
}

function createLocalConnectionMessage(
  content: string,
  files: File[],
  connectionId: string,
  attachments: ConnectionMessage["attachments"] = []
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
    attachments
  }
}
