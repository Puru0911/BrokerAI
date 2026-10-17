"use client"

import { useCallback, useLayoutEffect, useRef, type RefObject } from "react"

import {
  parseAttachmentPermission,
  parseAttachmentRequest,
  parseAttachmentShare
} from "@/components/chat/attachment-cards"
import { parseCandidateDeck } from "@/components/chat/candidate-card"
import { parseConnectOffer, parseContactCard } from "@/components/chat/contact-card"
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
  endRef,
  emptyTitle,
  emptyDetail
}: {
  messages: BrokerMessage[]
  bootLoading: boolean
  sessionLoading: boolean
  thinking: boolean
  error: string | null
  actions: MessageActions
  endRef: RefObject<HTMLDivElement | null>
  emptyTitle?: string
  emptyDetail?: string
}) {
  const showSkeleton = bootLoading || sessionLoading
  const scrollerRef = useRef<HTMLDivElement>(null)
  const lastMessageId = messages.at(-1)?.id

  const scrollToBottom = useCallback(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  }, [])

  useLayoutEffect(() => {
    scrollToBottom()
  }, [messages.length, lastMessageId, thinking, scrollToBottom])

  return (
    <div
      ref={scrollerRef}
      className="scrollbar-thin min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-4 py-6 sm:px-6"
    >
      <div className="mx-auto flex min-h-full w-full min-w-0 max-w-2xl flex-col gap-4">
        {error ? (
          <div className="rounded-2xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {showSkeleton ? (
          <ThreadSkeleton />
        ) : messages.length === 0 && !thinking ? (
          <EmptyState title={emptyTitle} detail={emptyDetail} />
        ) : (
          <>
            {clusterShareMessages(
              clusterCandidateMessages(
                placeCardsAfterAssistantText(
                  messages.filter((message) => !parseConnectOffer(message.content))
                )
              )
            ).map((group) => (
              <MessageBubble
                key={group[0].id}
                message={mergeShareGroup(group)}
                actions={actions}
              />
            ))}
            <ThinkingIndicator active={thinking} onShown={scrollToBottom} />
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

function isStructuredCard(message: BrokerMessage): boolean {
  if (message.role !== "assistant") return false
  return Boolean(
    parseAttachmentRequest(message.content) ||
      parseAttachmentPermission(message.content) ||
      parseAttachmentShare(message.content) ||
      parseContactCard(message.content) ||
      parseCandidateDeck(message.content)
  )
}

function placeCardsAfterAssistantText(messages: BrokerMessage[]): BrokerMessage[] {
  const ordered: BrokerMessage[] = []
  let index = 0
  while (index < messages.length) {
    const current = messages[index]
    if (current.role !== "assistant") {
      ordered.push(current)
      index += 1
      continue
    }
    const run: BrokerMessage[] = []
    while (index < messages.length && messages[index].role === "assistant") {
      run.push(messages[index])
      index += 1
    }
    ordered.push(
      ...run.filter((message) => !isStructuredCard(message)),
      ...run.filter((message) => isStructuredCard(message))
    )
  }
  return ordered
}

function isCandidateMessage(message: BrokerMessage): boolean {
  return message.role === "assistant" && Boolean(parseCandidateDeck(message.content))
}

function clusterCandidateMessages(messages: BrokerMessage[]): BrokerMessage[] {
  const result: BrokerMessage[] = []
  let index = 0
  while (index < messages.length) {
    if (!isCandidateMessage(messages[index])) {
      result.push(messages[index])
      index += 1
      continue
    }
    const run: BrokerMessage[] = []
    while (index < messages.length && isCandidateMessage(messages[index])) {
      run.push(messages[index])
      index += 1
    }
    result.push(mergeCandidateGroup(run))
  }
  return result
}

function mergeCandidateGroup(group: BrokerMessage[]): BrokerMessage {
  if (group.length === 1) return group[0]
  const candidates = group.flatMap(
    (message) => parseCandidateDeck(message.content)?.candidates || []
  )
  return {
    ...group[0],
    content: JSON.stringify({
      kind: "broker_candidate_cards",
      version: 1,
      candidates
    })
  }
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
