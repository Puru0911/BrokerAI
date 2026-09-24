"use client"

import type { RefObject } from "react"

import { parseAttachmentShare } from "@/components/chat/attachment-cards"
import { EmptyState } from "@/components/chat/empty-state"
import { MessageBubble, type MessageActions } from "@/components/chat/message-bubble"
import { ThinkingIndicator } from "@/components/chat/thinking-indicator"
import { ThreadSkeleton } from "@/components/chat/thread-skeleton"
import type { BrokerMessage } from "@/lib/api/broker"

export function MessageList({
  messages,
  bootLoading,
  sessionLoading,
  thinking,
  error,
  actions,
  endRef
}: {
  messages: BrokerMessage[]
  bootLoading: boolean
  sessionLoading: boolean
  thinking: boolean
  error: string | null
  actions: MessageActions
  endRef: RefObject<HTMLDivElement | null>
}) {
  const showSkeleton = bootLoading || sessionLoading

  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div className="mx-auto flex min-h-full max-w-2xl flex-col gap-4">
        {error ? (
          <div className="rounded-2xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {showSkeleton ? (
          <ThreadSkeleton />
        ) : messages.length === 0 && !thinking ? (
          <EmptyState />
        ) : (
          <>
            {clusterShareMessages(messages).map((group) => (
              <MessageBubble
                key={group[0].id}
                message={mergeShareGroup(group)}
                actions={actions}
              />
            ))}
            <ThinkingIndicator active={thinking} />
          </>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function isShareMessage(message: BrokerMessage): boolean {
  return message.role === "assistant" && Boolean(parseAttachmentShare(message.content))
}

function clusterShareMessages(messages: BrokerMessage[]): BrokerMessage[][] {
  const groups: BrokerMessage[][] = []
  for (const message of messages) {
    const previous = groups.at(-1)
    if (previous && isShareMessage(previous[0]) && isShareMessage(message)) {
      previous.push(message)
    } else {
      groups.push([message])
    }
  }
  return groups
}

function galleryTitle(titles: string[]): string {
  const stripped = titles
    .map((title) => title.replace(/\s+photo\s+\d+\s*$/i, "").trim())
    .filter(Boolean)
  if (stripped.length > 0 && stripped.every((title) => title === stripped[0])) {
    return stripped[0]
  }
  if (titles.length > 1) return "Photos"
  return titles[0] || "Shared files"
}

function mergeShareGroup(group: BrokerMessage[]): BrokerMessage {
  if (group.length === 1) return group[0]
  const payloads = group
    .map((message) => parseAttachmentShare(message.content))
    .filter((payload) => payload !== null)
  const attachments = group.flatMap((message) => message.attachments || [])
  const seen = new Set<string>()
  const unique = attachments.filter((item) => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
  const mergedPayload = {
    kind: "broker_attachment_share" as const,
    version: 1 as const,
    match_id: payloads[0]?.match_id || "",
    title: galleryTitle(payloads.map((payload) => payload.title).filter(Boolean)),
    attachments: unique.map((item) => ({
      id: item.id,
      kind: item.kind,
      label: item.label,
      purpose: item.purpose,
      content_type: item.content_type,
      original_filename: item.original_filename,
      url: item.url
    }))
  }
  return {
    ...group[0],
    content: JSON.stringify(mergedPayload),
    attachments: unique
  }
}
