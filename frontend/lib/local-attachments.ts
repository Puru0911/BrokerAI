import type {
  BrokerAttachment,
  BrokerMessage,
  ConnectionAttachment
} from "@/lib/api/broker"

export const MAX_UPLOAD_FILES = 10

const URL_RE = /https?:\/\/[^\s<>"']+/gi

export function extractUrls(text: string): string[] {
  const found: string[] = []
  for (const match of text.match(URL_RE) || []) {
    const cleaned = match.replace(/[.,);]+$/, "")
    if (cleaned && !found.includes(cleaned)) found.push(cleaned)
  }
  return found
}

function genericLocalLabel(contentType: string | null): string {
  const type = (contentType || "").toLowerCase()
  if (type.startsWith("image/")) return "Photo"
  if (type === "application/pdf") return "PDF"
  if (type.includes("word")) return "Document"
  return "File"
}

export function filesToConnectionAttachments(
  files: File[],
  connectionId: string
): ConnectionAttachment[] {
  return files.map((file, index) => ({
    id: `local-file-${Date.now()}-${index}`,
    connection_id: connectionId,
    message_id: null,
    kind: file.type.startsWith("image/") ? "image" : "file",
    original_filename: file.name,
    content_type: file.type || guessContentType(file.name),
    size_bytes: file.size,
    content_url: URL.createObjectURL(file),
    created_at: new Date().toISOString()
  }))
}

export function filesToLocalAttachments(
  files: File[],
  sessionId: string | null,
  caption?: string | null
): BrokerAttachment[] {
  const note = caption?.trim() || null
  return files.map((file, index) => {
    const contentType = file.type || guessContentType(file.name)
    return {
      id: `local-file-${Date.now()}-${index}`,
      session_id: sessionId ?? "local",
      kind: "file",
      share_class: "pending",
      label: genericLocalLabel(contentType),
      purpose: null,
      original_filename: file.name,
      content_type: contentType,
      size_bytes: file.size,
      url: null,
      content_url: URL.createObjectURL(file),
      caption: note,
      description: null,
      status: "ready",
      created_at: new Date().toISOString()
    }
  })
}

export function linkToLocalAttachment(
  url: string,
  sessionId: string | null,
  caption?: string | null
): BrokerAttachment {
  let host = url
  try {
    host = new URL(url).host
  } catch {
    host = url
  }
  return {
    id: `local-link-${Date.now()}`,
    session_id: sessionId ?? "local",
    kind: "url",
    share_class: "pending",
    label: host,
    purpose: null,
    original_filename: null,
    content_type: null,
    size_bytes: null,
    url,
    content_url: null,
    caption: caption?.trim() || null,
    description: null,
    status: "ready",
    created_at: new Date().toISOString()
  }
}

export function localAttachmentsForSend(options: {
  files: File[]
  link: string
  content: string
  sessionId: string | null
}): BrokerAttachment[] {
  const items = filesToLocalAttachments(
    options.files,
    options.sessionId,
    options.content
  )
  const urls = [
    ...(options.link.trim() ? [options.link.trim()] : []),
    ...extractUrls(options.content)
  ]
  const seen = new Set<string>()
  for (const url of urls) {
    if (seen.has(url)) continue
    seen.add(url)
    items.push(linkToLocalAttachment(url, options.sessionId, options.content))
  }
  return items
}

export function sortChatMessages<
  T extends { id: string; created_at: string; role?: string }
>(messages: T[]): T[] {
  return [...messages].sort((left, right) => {
    const time = left.created_at.localeCompare(right.created_at)
    if (time !== 0) return time
    const leftUser = left.role === "user" ? 0 : 1
    const rightUser = right.role === "user" ? 0 : 1
    if (leftUser !== rightUser) return leftUser - rightUser
    return left.id.localeCompare(right.id)
  })
}

export function hydrateMessagesWithAttachments(
  messages: BrokerMessage[],
  sessionAttachments?: BrokerAttachment[] | null
): BrokerMessage[] {
  const hydrated = !sessionAttachments?.length
    ? messages
    : messages.map((message) => {
        if (message.attachments && message.attachments.length > 0) return message
        const extras = sessionAttachments.filter(
          (item) => item.message_id === message.id
        )
        return extras.length ? { ...message, attachments: extras } : message
      })
  return sortChatMessages(hydrated)
}

export function mergeIncomingAttachments(
  incoming: { role: string; attachments?: BrokerAttachment[] },
  pending: BrokerAttachment[] | undefined
): BrokerAttachment[] {
  if (incoming.attachments && incoming.attachments.length > 0) {
    return incoming.attachments
  }
  if (incoming.role === "user" && pending?.length) {
    return pending
  }
  return incoming.attachments || []
}

function guessContentType(name: string): string | null {
  const lower = name.toLowerCase()
  if (lower.endsWith(".pdf")) return "application/pdf"
  if (lower.endsWith(".png")) return "image/png"
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg"
  if (lower.endsWith(".webp")) return "image/webp"
  if (lower.endsWith(".heic") || lower.endsWith(".heif")) return "image/heic"
  if (lower.endsWith(".docx")) {
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  }
  return null
}
