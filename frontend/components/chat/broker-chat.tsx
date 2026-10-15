"use client"

import { FormEvent, useEffect, useMemo, useRef, useState } from "react"

import { logout } from "@/app/app/actions"
import { parseAttachmentPermission } from "@/components/chat/attachment-cards"
import { ChatComposer } from "@/components/chat/chat-composer"
import { ChatHeader } from "@/components/chat/chat-header"
import { ConnectionThread } from "@/components/chat/connection-thread"
import { MatchLaneRail } from "@/components/chat/match-lane-rail"
import { MessageList } from "@/components/chat/message-list"
import { SessionSidebar } from "@/components/chat/session-sidebar"
import {
  type BrokerMatchLane,
  type BrokerMessage,
  type BrokerSession,
  type BrokerSessionDetail,
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
  markBrokerMatchRead,
  respondToIntroduction,
  sendBrokerMessage,
  sendConnectionMessage,
  uploadBrokerAttachment,
  uploadConnectionAttachment
} from "@/lib/api/broker"
import { connectBrokerSocket } from "@/lib/chat-socket"
import {
  MAX_UPLOAD_FILES,
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
import { patchNotifyEmail } from "@/lib/api/users"
import { formatStatus } from "@/lib/chat-format"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

type BrokerChatProps = {
  initialAccessToken: string
  userName: string
  userEmail: string
  notifyEmail?: boolean
}

const NEW_SESSION_THINKING = "new"

export function BrokerChat({
  initialAccessToken,
  userName,
  userEmail,
  notifyEmail = true
}: BrokerChatProps) {
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
  const [thinkingLanes, setThinkingLanes] = useState<Record<string, number>>(
    {}
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
  const [matches, setMatches] = useState<BrokerMatchLane[]>([])
  const [activeMatchId, setActiveMatchId] = useState<string | null>(null)
  const [introducingMatchId, setIntroducingMatchId] = useState<string | null>(
    null
  )
  const [error, setError] = useState<string | null>(null)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null
  )
  const [showNotifyPrompt, setShowNotifyPrompt] = useState(false)
  const [notifyBusy, setNotifyBusy] = useState(false)
  const [emailNotify, setEmailNotify] = useState(notifyEmail)
  const [emailNotifyBusy, setEmailNotifyBusy] = useState(false)

  const activeSession = sessions.find(
    (session) => session.id === activeSessionId
  )
  const activeConnection = connections.find(
    (connection) => connection.id === activeConnectionId
  )
  const visibleMessages = [...messages, ...pendingMessages].filter(
    (message) =>
      sameLane(message.match_id, activeMatchId) &&
      (message.session_id === activeSessionId ||
        message.session_id === "local" ||
        !activeSessionId)
  )
  const lanePending = pendingMessages.filter((message) =>
    sameLane(message.match_id, activeMatchId)
  )
  const activeMatch = matches.find((match) => match.id === activeMatchId) ?? null
  const laneConnectOffer = activeMatch?.connect_offer ?? null
  const otherLaneAlerts = matches.filter(
    (match) => match.id !== activeMatchId && laneAlert(match)
  )
  const visibleConnectionMessages = [
    ...connectionMessages,
    ...pendingConnectionMessages
  ]
  const connectedMatchIds = useMemo(
    () => new Set(connections.map((connection) => connection.match_id)),
    [connections]
  )
  const viewingConnection = Boolean(activeConnectionId)
  const replyAlreadyVisible =
    lanePending.length === 0 &&
    visibleMessages.at(-1)?.role === "assistant"
  const activeLaneKey = laneKey(activeSessionId, activeMatchId)
  const thinking =
    Boolean(
      thinkingLanes[activeLaneKey] ||
        thinkingLanes[laneKey(NEW_SESSION_THINKING, activeMatchId)]
    ) &&
    !viewingConnection &&
    !replyAlreadyVisible
  const composerLocked =
    bootLoading || sessionLoading || connectionLoading || !accessToken
  const composerBusy = viewingConnection ? sending : thinking
  const activeSessionIdRef = useRef(activeSessionId)
  activeSessionIdRef.current = activeSessionId
  const activeMatchIdRef = useRef(activeMatchId)
  activeMatchIdRef.current = activeMatchId
  const activeConnectionIdRef = useRef(activeConnectionId)
  activeConnectionIdRef.current = activeConnectionId
  const thinkingTurnRef = useRef(0)
  const thinkingLanesRef = useRef(thinkingLanes)
  thinkingLanesRef.current = thinkingLanes
  const pendingReadMatchIdsRef = useRef(new Set<string>())

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

        const params = new URLSearchParams(window.location.search)
        const chatId = params.get("chat")
        const sessionParam = params.get("session")
        const matchParam = params.get("match")
        if (chatId && connectionList.some((item) => item.id === chatId)) {
          setActiveConnectionId(chatId)
          setConnectionLoading(true)
          setPendingChatId(chatId)
          return
        }

        if (sessionList.length > 0) {
          const sessionId =
            sessionParam && sessionList.some((item) => item.id === sessionParam)
              ? sessionParam
              : sessionList[0].id
          const detail = await getBrokerSession(token, sessionId)
          if (activeSessionIdRef.current && activeSessionIdRef.current !== sessionId) {
            return
          }
          setActiveSessionId(detail.session.id)
          const lanes = detail.matches ?? detail.session.matches ?? []
          if (matchParam && lanes.some((lane) => lane.id === matchParam)) {
            setActiveMatchId(matchParam)
            activeMatchIdRef.current = matchParam
            noteMatchRead(pendingReadMatchIdsRef.current, matchParam)
          }
          applySessionDetail(detail)
          if (matchParam && lanes.some((lane) => lane.id === matchParam)) {
            await markBrokerMatchRead(token, matchParam).catch(() => undefined)
          }
          setPendingMessages([])
        } else {
          setActiveSessionId(null)
          activeSessionIdRef.current = null
          setActiveMatchId(null)
          activeMatchIdRef.current = null
          setMessages([])
          setMatches([])
          setPendingMessages([])
          setSessionQuery(null, null)
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
      const busy = Object.keys(thinkingLanesRef.current).some((key) =>
        key.startsWith(`${sessionId}:`)
      )
      if (busy) return
      void getBrokerSession(accessToken, sessionId)
        .then((detail) => {
          if (cancelled) return
          if (activeSessionIdRef.current !== sessionId) return
          if (activeConnectionIdRef.current) return
          if (detail.session.id !== sessionId) return
          applySessionDetail(detail)
        })
        .catch(() => undefined)
    }, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessToken, activeSessionId, viewingConnection])

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

  async function handleToggleEmailNotify() {
    if (!accessToken || emailNotifyBusy) return
    const next = !emailNotify
    setEmailNotifyBusy(true)
    setEmailNotify(next)
    try {
      const profile = await patchNotifyEmail(accessToken, next)
      setEmailNotify(profile.notify_email)
    } catch (caughtError) {
      setEmailNotify(!next)
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not update email settings."
      )
    } finally {
      setEmailNotifyBusy(false)
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
      url.searchParams.delete("session")
      url.searchParams.delete("match")
    } else {
      url.searchParams.delete("chat")
    }
    window.history.replaceState(null, "", url.pathname + url.search)
  }

  function setSessionQuery(sessionId: string | null, matchId: string | null) {
    const url = new URL(window.location.href)
    url.searchParams.delete("chat")
    if (sessionId) url.searchParams.set("session", sessionId)
    else url.searchParams.delete("session")
    if (matchId) url.searchParams.set("match", matchId)
    else url.searchParams.delete("match")
    window.history.replaceState(null, "", url.pathname + url.search)
  }

  function applySessionDetail(detail: BrokerSessionDetail) {
    setMessages(
      hydrateMessagesWithAttachments(detail.messages, detail.attachments)
    )
    const focus = activeMatchIdRef.current
    const incoming = detail.matches ?? detail.session.matches ?? []
    const focused = incoming.find((lane) => lane.id === focus)
    if (focus && focused && focused.unread_count > 0 && accessToken) {
      noteMatchRead(pendingReadMatchIdsRef.current, focus)
      void markBrokerMatchRead(accessToken, focus).catch(() => undefined)
    }
    const lanes = applyLaneReadState(incoming, focus, pendingReadMatchIdsRef.current)
    setMatches(lanes)
    setSessions((current) =>
      current.map((session) =>
        session.id === detail.session.id
          ? {
              ...detail.session,
              matches: lanes,
              match_unread_count: matchUnreadTotal(lanes)
            }
          : session
      )
    )
    if (focus && !lanes.some((lane) => lane.id === focus)) {
      setActiveMatchId(null)
      activeMatchIdRef.current = null
    }
  }

  function dropPendingMessage(messageId: string) {
    setPendingMessages((current) =>
      current.filter((message) => message.id !== messageId)
    )
  }

  function beginLaneThinking(
    sessionId: string | null,
    matchId: string | null,
    turn: number
  ) {
    setThinkingLanes((current) => ({
      ...current,
      [laneKey(sessionId, matchId)]: turn
    }))
  }

  function retargetLaneThinking(
    fromSessionId: string,
    toSessionId: string,
    matchId: string | null,
    turn: number
  ) {
    setThinkingLanes((current) => {
      const next = { ...current }
      const from = laneKey(fromSessionId, matchId)
      if (next[from] === turn) delete next[from]
      next[laneKey(toSessionId, matchId)] = turn
      return next
    })
  }

  function endLaneThinking(
    sessionId: string | null,
    matchId: string | null,
    turn: number
  ) {
    const keys = [
      laneKey(sessionId, matchId),
      laneKey(NEW_SESSION_THINKING, matchId)
    ]
    setThinkingLanes((current) => {
      const next = { ...current }
      for (const key of keys) {
        if (next[key] === turn) delete next[key]
      }
      return next
    })
  }

  async function refreshSessions(token: string) {
    const sessionList = await listBrokerSessions(token)
    const focus = activeMatchIdRef.current
    const sessionId = activeSessionIdRef.current
    setSessions(
      sessionList.map((session) => {
        if (session.id !== sessionId) return session
        const lanes = applyLaneReadState(
          session.matches ?? [],
          focus,
          pendingReadMatchIdsRef.current
        )
        return {
          ...session,
          matches: lanes,
          match_unread_count: matchUnreadTotal(lanes)
        }
      })
    )
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

  function showDraftRequest() {
    setActiveSessionId(null)
    activeSessionIdRef.current = null
    setActiveConnectionId(null)
    activeConnectionIdRef.current = null
    setActiveMatchId(null)
    activeMatchIdRef.current = null
    setMessages([])
    setMatches([])
    setPendingMessages([])
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setSessionQuery(null, null)
  }

  function handleCreateSession() {
    if (!accessToken) return
    setError(null)
    showDraftRequest()
  }

  async function openBrokerSession(sessionId: string, matchId: string | null) {
    if (!accessToken) {
      setDrawerOpen(false)
      return
    }

    setError(null)
    setSessionLoading(true)
    setActiveSessionId(sessionId)
    activeSessionIdRef.current = sessionId
    setActiveConnectionId(null)
    setActiveMatchId(matchId)
    activeMatchIdRef.current = matchId
    setMessages([])
    setMatches([])
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setSessionQuery(sessionId, matchId)
    try {
      const detail = await getBrokerSession(accessToken, sessionId)
      if (activeSessionIdRef.current !== sessionId) return
      setActiveSessionId(detail.session.id)
      applySessionDetail(detail)
      if (matchId) {
        noteMatchRead(pendingReadMatchIdsRef.current, matchId)
        await markBrokerMatchRead(accessToken, matchId).catch(() => undefined)
      }
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

  async function handleSelectSession(sessionId: string) {
    if (!accessToken) {
      setDrawerOpen(false)
      return
    }
    if (sessionId === activeSessionId && !activeConnectionId) {
      handleSelectRequestLane()
      setDrawerOpen(false)
      return
    }
    await openBrokerSession(sessionId, null)
  }

  async function handleSelectMatch(sessionId: string, matchId: string) {
    if (!accessToken) return
    if (sessionId !== activeSessionId || activeConnectionId) {
      await openBrokerSession(sessionId, matchId)
      return
    }
    setActiveMatchId(matchId)
    activeMatchIdRef.current = matchId
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    setDrawerOpen(false)
    setSessionQuery(sessionId, matchId)
    noteMatchRead(pendingReadMatchIdsRef.current, matchId)
    setMatches((current) => {
      const lanes = applyLaneReadState(
        current,
        matchId,
        pendingReadMatchIdsRef.current
      )
      setSessions((sessions) =>
        sessions.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                matches: lanes,
                match_unread_count: matchUnreadTotal(lanes)
              }
            : session
        )
      )
      return lanes
    })
    await markBrokerMatchRead(accessToken, matchId).catch(() => undefined)
  }

  function handleSelectRequestLane() {
    setActiveMatchId(null)
    activeMatchIdRef.current = null
    setComposerValue("")
    setPendingFiles([])
    setPendingLink("")
    if (activeSessionId) setSessionQuery(activeSessionId, null)
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
    const sentMatchId = activeMatchId
    const optimisticMessage = createLocalUserMessage(
      content,
      activeSessionId,
      localAttachments,
      sentMatchId
    )
    setPendingMessages((current) => [
      ...current.filter((message) => message.id !== optimisticMessage.id),
      optimisticMessage
    ])
    let sessionId = activeSessionId
    const thinkingTurn = ++thinkingTurnRef.current
    beginLaneThinking(sessionId ?? NEW_SESSION_THINKING, sentMatchId, thinkingTurn)

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
        retargetLaneThinking(NEW_SESSION_THINKING, sessionId, sentMatchId, thinkingTurn)
        if (!files.length && !link) {
          if (activeSessionIdRef.current === sessionId) {
            setMessages(
              hydrateMessagesWithAttachments(detail.messages, detail.attachments)
            )
          }
          dropPendingMessage(optimisticMessage.id)
          endLaneThinking(sessionId, sentMatchId, thinkingTurn)
          return
        }
        if (detail.messages.length && activeSessionIdRef.current === sessionId) {
          setMessages(
            hydrateMessagesWithAttachments(detail.messages, detail.attachments)
          )
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
        dropPendingMessage(optimisticMessage.id)
        return
      }

      const newMessages = await sendBrokerMessage(
        accessToken,
        sessionId,
        content,
        attachmentIds,
        sentMatchId
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
      }
      dropPendingMessage(optimisticMessage.id)
      endLaneThinking(sessionId, sentMatchId, thinkingTurn)
      if (sentMatchId) {
        noteMatchRead(pendingReadMatchIdsRef.current, sentMatchId)
        await markBrokerMatchRead(accessToken, sentMatchId).catch(() => undefined)
      }
      await refreshSessions(accessToken)
      if (activeSessionIdRef.current === sessionId) {
        const detail = await getBrokerSession(accessToken, sessionId)
        if (activeSessionIdRef.current === sessionId) {
          applySessionDetail(detail)
        }
      }
    } catch (caughtError) {
      if (
        activeSessionIdRef.current === sessionId &&
        sameLane(activeMatchIdRef.current, sentMatchId)
      ) {
        setComposerValue(content)
        setPendingFiles(files)
        setPendingLink(link)
      }
      dropPendingMessage(optimisticMessage.id)
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not send your message."
      )
    } finally {
      endLaneThinking(sessionId, sentMatchId, thinkingTurn)
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

  async function handleRequestUpload(requestId: string, files: File[]) {
    if (!accessToken || !activeSessionId || files.length === 0) return
    const sessionId = activeSessionId
    const batch = files.slice(0, MAX_UPLOAD_FILES)
    setError(null)
    setUploadingRequestId(requestId)
    const localAttachments = filesToLocalAttachments(batch, sessionId)
    const sentMatchId = activeMatchIdRef.current
    let thinkingTurn: number | null = null
    let optimisticId: string | null = null
    try {
      const uploadedIds: string[] = []
      for (const file of batch) {
        const uploaded = await uploadBrokerAttachment(
          accessToken,
          sessionId,
          file,
          { requestId }
        )
        uploadedIds.push(uploaded.id)
      }
      if (!uploadedIds.length) return
      setUploadingRequestId(null)
      thinkingTurn = ++thinkingTurnRef.current
      beginLaneThinking(sessionId, sentMatchId, thinkingTurn)
      const optimisticMessage = createLocalUserMessage(
        "",
        sessionId,
        localAttachments,
        sentMatchId
      )
      optimisticId = optimisticMessage.id
      setPendingMessages((current) => [
        ...current.filter((message) => message.id !== optimisticMessage.id),
        optimisticMessage
      ])
      const newMessages = await sendBrokerMessage(
        accessToken,
        sessionId,
        "",
        uploadedIds,
        sentMatchId
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
      }
      dropPendingMessage(optimisticMessage.id)
      endLaneThinking(sessionId, sentMatchId, thinkingTurn)
      await refreshSessions(accessToken)
    } catch (caughtError) {
      if (optimisticId) dropPendingMessage(optimisticId)
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not upload that file."
      )
    } finally {
      setUploadingRequestId(null)
      if (thinkingTurn !== null) {
        endLaneThinking(sessionId, sentMatchId, thinkingTurn)
      }
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
      const status = granted ? "granted" : "denied"
      if (sessionId && activeSessionIdRef.current === sessionId) {
        setMessages((current) =>
          current.map((message) => {
            const permission = parseAttachmentPermission(message.content)
            if (
              !permission ||
              permission.attachment_id !== attachmentId ||
              permission.match_id !== matchId
            ) {
              return message
            }
            return {
              ...message,
              content: JSON.stringify({ ...permission, status })
            }
          })
        )
      }
      if (!sessionId) return
      const detail = await getBrokerSession(accessToken, sessionId)
      if (activeSessionIdRef.current !== sessionId) return
      applySessionDetail(detail)
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
        setActiveMatchId(null)
        activeMatchIdRef.current = null
        if (remaining.length > 0) {
          setSessionLoading(true)
          const nextId = remaining[0].id
          const detail = await getBrokerSession(accessToken, nextId)
          if (activeSessionIdRef.current !== sessionId) return
          setActiveSessionId(detail.session.id)
          activeSessionIdRef.current = detail.session.id
          applySessionDetail(detail)
          setSessionQuery(detail.session.id, null)
        } else {
          showDraftRequest()
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

  async function handleIntroduction(
    matchId: string,
    action: "accept" | "dismiss"
  ) {
    if (!accessToken) return
    setError(null)
    setIntroducingMatchId(matchId)
    const sessionId = activeSessionId
    try {
      const detail = await respondToIntroduction(accessToken, matchId, action)
      if (!sessionId || activeSessionIdRef.current !== sessionId) return
      applySessionDetail(detail)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not update that introduction."
      )
    } finally {
      setIntroducingMatchId(null)
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

  const liveMatchCount = matches.filter(
    (match) => match.status !== "closed"
  ).length
  const requestBusy = Boolean(
    thinkingLanes[laneKey(activeSessionId, null)] ||
      thinkingLanes[laneKey(NEW_SESSION_THINKING, null)]
  )
  const busyMatchIds = matches
    .filter((match) => thinkingLanes[laneKey(activeSessionId, match.id)])
    .map((match) => match.id)
  const laneConnectionId =
    activeMatch?.connection_id ||
    connections.find((item) => item.match_id === activeMatch?.id)?.id ||
    null
  const headerTitle = viewingConnection
    ? activeConnection?.peer.name ?? "Chat"
    : activeMatch
      ? activeMatch.label
      : (activeSession?.title ?? "New request")
  const headerStatus = viewingConnection
    ? activeConnection?.peer.request_title || "Direct chat"
    : activeMatch
      ? `${formatLaneStatus(activeMatch)} · ${activeSession?.title ?? "Request"}`
      : liveMatchCount
        ? `${liveMatchCount} match${liveMatchCount === 1 ? "" : "es"} in progress`
        : (activeSession?.status ?? "Start with a message")

  return (
    <main className="flex h-screen overflow-hidden bg-canvas text-ink">
      <SessionSidebar
        open={drawerOpen}
        userName={userName}
        userEmail={userEmail}
        sessions={sessions}
        connections={connections}
        activeSessionId={activeSessionId}
        activeMatchId={activeMatchId}
        activeConnectionId={activeConnectionId}
        deletingSessionId={deletingSessionId}
        onCreateSession={() => void handleCreateSession()}
        onSelectSession={(sessionId) => void handleSelectSession(sessionId)}
        onSelectMatch={(sessionId, matchId) =>
          void handleSelectMatch(sessionId, matchId)
        }
        onSelectConnection={(connectionId) =>
          void handleSelectConnection(connectionId)
        }
        onDeleteSession={(sessionId) => void handleDeleteSession(sessionId)}
        emailNotify={emailNotify}
        emailNotifyBusy={emailNotifyBusy}
        onToggleEmailNotify={() => void handleToggleEmailNotify()}
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
          action={
            laneConnectionId && activeMatch ? (
              <button
                type="button"
                onClick={() => handleOpenChat(activeMatch.id)}
                className="h-9 rounded-xl bg-accent px-3 text-xs font-semibold text-surface transition hover:bg-accent-hover"
              >
                Open chat
              </button>
            ) : null
          }
        />

        {!viewingConnection ? (
          <MatchLaneRail
            requestTitle={activeSession?.title ?? "Your request"}
            matches={matches}
            activeMatchId={activeMatchId}
            requestBusy={requestBusy}
            busyMatchIds={busyMatchIds}
            onSelectRequest={handleSelectRequestLane}
            onSelectMatch={(matchId) => {
              if (activeSessionId) void handleSelectMatch(activeSessionId, matchId)
            }}
          />
        ) : null}

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
                className="h-8 rounded-lg bg-accent px-3 text-xs font-semibold text-surface transition hover:bg-accent-hover disabled:opacity-50"
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
            emptyTitle={activeMatch ? matchEmptyTitle(activeMatch) : undefined}
            emptyDetail={activeMatch ? matchEmptyDetail(activeMatch) : undefined}
            actions={{
              accessToken,
              connectingMatchId,
              connectedMatchIds,
              onConnect: (matchId) => void handleConnect(matchId),
              onOpenChat: handleOpenChat,
              uploadingRequestId,
              onRequestUpload: (requestId, files) =>
                void handleRequestUpload(requestId, files),
              grantingAttachmentId,
              onGrant: (attachmentId, matchId, granted) =>
                void handleGrant(attachmentId, matchId, granted)
            }}
            endRef={messageEndRef}
          />
        )}

        {!viewingConnection && !activeMatch && otherLaneAlerts.length > 0 ? (
          <div className="mx-auto w-full max-w-2xl shrink-0 px-4 sm:px-6">
            <div className="mb-2 space-y-2">
              {otherLaneAlerts.map((match) => {
                const alert = laneAlert(match)
                if (!alert) return null
                return (
                  <button
                    key={match.id}
                    type="button"
                    onClick={() => {
                      if (activeSessionId) void handleSelectMatch(activeSessionId, match.id)
                    }}
                    className="flex w-full items-center justify-between gap-3 rounded-2xl border border-line bg-accent-soft px-4 py-3 text-left"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">
                        {alert.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted">
                        {alert.detail}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-semibold text-accent">
                      Open
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        ) : null}

        {!viewingConnection && laneConnectOffer ? (
          <div className="mx-auto w-full max-w-2xl shrink-0 px-4 sm:px-6">
            <div className="mb-2 rounded-2xl border border-line bg-accent-soft px-4 py-3">
              <p className="text-sm leading-6 text-ink">{laneConnectOffer.prompt}</p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={introducingMatchId === laneConnectOffer.match_id}
                  onClick={() =>
                    void handleIntroduction(laneConnectOffer.match_id, "accept")
                  }
                  className="h-9 flex-1 rounded-xl bg-accent px-3 text-xs font-semibold text-surface transition hover:bg-accent-hover disabled:opacity-50"
                >
                  {introducingMatchId === laneConnectOffer.match_id
                    ? "Working…"
                    : "Introduce us"}
                </button>
                <button
                  type="button"
                  disabled={introducingMatchId === laneConnectOffer.match_id}
                  onClick={() =>
                    void handleIntroduction(laneConnectOffer.match_id, "dismiss")
                  }
                  className="h-9 rounded-xl px-3 text-xs font-medium text-muted transition hover:text-ink disabled:opacity-50"
                >
                  Not yet
                </button>
              </div>
            </div>
          </div>
        ) : null}

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
                : activeMatch?.status === "closed"
                  ? "This match is closed. You can still ask the broker about it…"
                  : activeMatch
                    ? `Talk with the broker about ${activeMatch.label}…`
                    : "Describe what you need, or attach a file…"
            }
            showLink={!viewingConnection}
          />
        </div>
      </section>
    </main>
  )
}

function formatLaneStatus(match: BrokerMatchLane) {
  if (match.status === "connected") return "Connected"
  if (match.status === "accepted") return "Ready to connect"
  if (match.status === "closed") return "Closed"
  if (match.waiting) return "Waiting on you"
  return "In progress"
}

function sameLane(left: string | null | undefined, right: string | null | undefined) {
  return (left || null) === (right || null)
}

function laneKey(
  sessionId: string | null | undefined,
  matchId: string | null | undefined
) {
  return `${sessionId ?? NEW_SESSION_THINKING}:${matchId || "request"}`
}

function noteMatchRead(
  pendingRead: Set<string>,
  matchId: string | null | undefined
) {
  if (matchId) pendingRead.add(matchId)
}

function applyLaneReadState(
  lanes: BrokerMatchLane[],
  focus: string | null,
  pendingRead: Set<string>
) {
  return lanes.map((lane) => {
    if (lane.unread_count === 0) {
      pendingRead.delete(lane.id)
      return lane
    }
    if ((focus && lane.id === focus) || pendingRead.has(lane.id)) {
      return { ...lane, unread_count: 0 }
    }
    return lane
  })
}

function matchUnreadTotal(lanes: BrokerMatchLane[]) {
  return lanes.reduce((sum, lane) => sum + lane.unread_count, 0)
}

function laneAlert(match: BrokerMatchLane) {
  if (match.connect_offer) {
    return {
      title: `${match.label} is ready to be introduced`,
      detail: "Open that match to continue."
    }
  }
  if (match.unread_count > 0) {
    return {
      title: `There's an update on ${match.label}`,
      detail: "Open that match to read it."
    }
  }
  return null
}

function matchEmptyTitle(match: BrokerMatchLane) {
  if (match.status === "closed") {
    return match.close_reason
      ? `This match is closed (${formatStatus(match.close_reason)}).`
      : "This match is closed."
  }
  if (match.status === "connected") {
    return `You're connected. This broker thread is still about ${match.label}.`
  }
  return `This is your private conversation with the broker about ${match.label}.`
}

function matchEmptyDetail(match: BrokerMatchLane) {
  if (match.status === "closed") {
    return "You can still ask the broker what happened. Other matches on this request stay open."
  }
  if (match.status === "connected") {
    return "Open chat to talk to them directly, or keep using this thread with the broker."
  }
  return "Ask questions, share files, or wait for an update. This thread stays separate from your other matches."
}

function createLocalUserMessage(
  content: string,
  sessionId: string | null,
  attachments: BrokerMessage["attachments"] = [],
  matchId: string | null = null
): BrokerMessage {
  return {
    id: `local-user-${Date.now()}`,
    session_id: sessionId ?? "local",
    match_id: matchId,
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
