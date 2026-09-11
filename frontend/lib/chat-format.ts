export function formatStatus(status: string) {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

export function formatSessionTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value))
}

export function connectionPreview(content: string | null | undefined, hasAttachments = false) {
  const text = (content || "").trim()
  if (text) return text
  if (hasAttachments) return "Attachment"
  return "Connected"
}
