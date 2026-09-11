"use client"

import type { RefObject } from "react"

import { AttachmentStack } from "@/components/chat/attachment-cards"
import { ThreadSkeleton } from "@/components/chat/thread-skeleton"
import { cn } from "@/lib/cn"
import type { ConnectionMessage } from "@/lib/api/broker"

export function ConnectionThread({
  messages,
  loading,
  error,
  peerName,
  endRef
}: {
  messages: ConnectionMessage[]
  loading: boolean
  error: string | null
  peerName: string
  endRef: RefObject<HTMLDivElement | null>
}) {
  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div className="mx-auto flex min-h-full max-w-2xl flex-col gap-4">
        {error ? (
          <div className="rounded-2xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {loading ? (
          <ThreadSkeleton />
        ) : messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
            <p className="max-w-sm text-base leading-7 text-ink">
              Say hello to {peerName}.
            </p>
          </div>
        ) : (
          messages.map((message) => (
            <ConnectionBubble key={message.id} message={message} />
          ))
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function ConnectionBubble({ message }: { message: ConnectionMessage }) {
  if (message.kind === "system") {
    return (
      <div className="px-6 py-1 text-center text-xs leading-5 text-muted">
        {message.content}
      </div>
    )
  }

  const attachments = message.attachments || []

  return (
    <div className={cn("flex", message.mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "min-w-0 max-w-[min(82%,36rem)] space-y-3 px-4 py-3 text-sm leading-6",
          message.mine
            ? "rounded-3xl rounded-br-md bg-user text-white"
            : "rounded-3xl rounded-bl-md border border-line bg-surface text-ink"
        )}
      >
        {message.content ? (
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {message.content}
          </div>
        ) : null}
        {attachments.length ? (
          <AttachmentStack attachments={attachments} inverted={message.mine} />
        ) : null}
      </div>
    </div>
  )
}
