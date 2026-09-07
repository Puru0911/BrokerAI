export type BrokerSession = {
  id: string
  title: string
  status: string
  summary: string | null
  created_at: string
  updated_at: string
}

export type BrokerAttachment = {
  id: string
  session_id: string
  kind: "file" | "url"
  share_class: "pending" | "public" | "personal"
  label: string | null
  purpose: string | null
  original_filename: string | null
  content_type: string | null
  size_bytes: number | null
  url: string | null
  content_url: string | null
  description: string | null
  status: string
  created_at: string
}

export type BrokerUploadRequest = {
  id: string
  purpose: string
  suggested_share_class: string
  hint: string
  status: string
  created_at: string
}

export type BrokerMessage = {
  id: string
  session_id: string
  role: "assistant" | "user"
  content: string
  created_at: string
  attachments?: BrokerAttachment[]
}

export type BrokerPartyConnection = {
  id: string
  match_id: string
  source_user_id: string
  candidate_user_id: string
  status: string
  created_at: string
  updated_at: string
}

export type BrokerSessionDetail = {
  session: BrokerSession
  messages: BrokerMessage[]
  attachments?: BrokerAttachment[]
  pending_upload_requests?: BrokerUploadRequest[]
}

function getBackendUrl() {
  return (
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    process.env.BACKEND_URL ||
    "http://127.0.0.1:8000"
  )
}

async function brokerFetch<T>(
  accessToken: string,
  path: string,
  init?: RequestInit
) {
  const response = await fetch(`${getBackendUrl()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...init?.headers
    }
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : `Broker API failed with status ${response.status}`
    throw new Error(detail)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function listBrokerSessions(accessToken: string) {
  return brokerFetch<BrokerSession[]>(accessToken, "/broker/sessions")
}

export function createBrokerSession(
  accessToken: string,
  initialMessage?: string
) {
  return brokerFetch<BrokerSessionDetail>(accessToken, "/broker/sessions", {
    method: "POST",
    body: JSON.stringify({ initial_message: initialMessage || null })
  })
}

export function getBrokerSession(accessToken: string, sessionId: string) {
  return brokerFetch<BrokerSessionDetail>(
    accessToken,
    `/broker/sessions/${sessionId}`
  )
}

export function deleteBrokerSession(accessToken: string, sessionId: string) {
  return brokerFetch<void>(accessToken, `/broker/sessions/${sessionId}`, {
    method: "DELETE"
  })
}

export function sendBrokerMessage(
  accessToken: string,
  sessionId: string,
  content: string,
  attachmentIds: string[] = []
) {
  return brokerFetch<BrokerMessage[]>(
    accessToken,
    `/broker/sessions/${sessionId}/messages`,
    {
      method: "POST",
      body: JSON.stringify({
        content,
        attachment_ids: attachmentIds
      })
    }
  )
}

export async function uploadBrokerAttachment(
  accessToken: string,
  sessionId: string,
  file: File,
  options?: { caption?: string; requestId?: string }
) {
  const body = new FormData()
  body.append("file", file)
  if (options?.caption) body.append("caption", options.caption)
  if (options?.requestId) body.append("request_id", options.requestId)

  const response = await fetch(
    `${getBackendUrl()}/broker/sessions/${sessionId}/attachments`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`
      },
      body
    }
  )
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : `Upload failed with status ${response.status}`
    throw new Error(detail)
  }
  return (await response.json()) as BrokerAttachment
}

export function addBrokerLink(
  accessToken: string,
  sessionId: string,
  url: string,
  options?: { caption?: string; requestId?: string }
) {
  return brokerFetch<BrokerAttachment>(
    accessToken,
    `/broker/sessions/${sessionId}/links`,
    {
      method: "POST",
      body: JSON.stringify({
        url,
        caption: options?.caption || null,
        request_id: options?.requestId || null
      })
    }
  )
}

export function grantBrokerAttachment(
  accessToken: string,
  attachmentId: string,
  matchId: string,
  granted: boolean
) {
  return brokerFetch<BrokerAttachment>(
    accessToken,
    `/broker/attachments/${attachmentId}/grants`,
    {
      method: "POST",
      body: JSON.stringify({ match_id: matchId, granted })
    }
  )
}

export function connectBrokerMatch(accessToken: string, matchId: string) {
  return brokerFetch<BrokerPartyConnection>(
    accessToken,
    `/broker/matches/${matchId}/connect`,
    {
      method: "POST"
    }
  )
}
