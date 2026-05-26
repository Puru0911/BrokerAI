export type BrokerSession = {
  id: string
  title: string
  status: string
  summary: string | null
  created_at: string
  updated_at: string
}

export type BrokerMessage = {
  id: string
  session_id: string
  role: "assistant" | "user"
  content: string
  created_at: string
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

export function sendBrokerMessage(
  accessToken: string,
  sessionId: string,
  content: string
) {
  return brokerFetch<BrokerMessage[]>(
    accessToken,
    `/broker/sessions/${sessionId}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ content })
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
