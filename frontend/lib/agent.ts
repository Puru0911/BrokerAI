export const AGENT_NAME =
  (process.env.NEXT_PUBLIC_AGENT_NAME || "BrokerAI").trim() || "BrokerAI"

export function agentNameParts(name: string = AGENT_NAME): {
  lead: string
  accent: string
} {
  const trimmed = name.trim() || "BrokerAI"
  if (trimmed.length > 2 && /AI$/i.test(trimmed)) {
    return { lead: trimmed.slice(0, -2), accent: trimmed.slice(-2) }
  }
  return { lead: trimmed, accent: "" }
}

export function welcomeMessage(name: string = AGENT_NAME): string {
  return `Hi! I'm ${name}. Tell me what you're looking for and I'll find you the right person.`
}
