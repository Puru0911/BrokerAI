"use client"

import type { RefObject } from "react"

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
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} actions={actions} />
            ))}
            <ThinkingIndicator active={thinking} />
          </>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}
