"use client"

import {
  AttachmentPermissionCard,
  AttachmentRequestCard,
  AttachmentShareCard,
  AttachmentStack,
  parseAttachmentPermission,
  parseAttachmentRequest,
  parseAttachmentShare
} from "@/components/chat/attachment-cards"
import { ChatText } from "@/components/chat/chat-text"
import { CandidateDeck, parseCandidateDeck } from "@/components/chat/candidate-card"
import { ContactCard, parseContactCard } from "@/components/chat/contact-card"
import { cn } from "@/lib/cn"
import type { BrokerMessage } from "@/lib/api/broker"

export type MessageActions = {
  accessToken: string | null
  connectingMatchId: string | null
  connectedMatchIds: Set<string>
  onConnect: (matchId: string) => void
  onOpenChat?: (matchId: string) => void
  uploadingRequestId: string | null
  onRequestUpload: (requestId: string, files: File[]) => void
  grantingAttachmentId: string | null
  onGrant: (attachmentId: string, matchId: string, granted: boolean) => void
  suggestingId: string | null
  onSuggestion: (
    suggestionId: string,
    action: "interested" | "skip",
    attachmentId?: string
  ) => void
}

export function MessageBubble({
  message,
  actions
}: {
  message: BrokerMessage
  actions: MessageActions
}) {
  const isUser = message.role === "user"
  const contactCard = parseContactCard(message.content)
  const requestCard = parseAttachmentRequest(message.content)
  const permissionCard = parseAttachmentPermission(message.content)
  const shareCard = parseAttachmentShare(message.content)
  const candidateDeck = parseCandidateDeck(message.content)
  const attachments = message.attachments || []
  const hidePlainText = Boolean(
    contactCard || requestCard || permissionCard || shareCard || candidateDeck
  )
  const isStructured = hidePlainText
  const isCandidateDeck = Boolean(candidateDeck && !isUser)

  return (
    <div
      className={cn(
        "flex w-full min-w-0 max-w-full",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "box-border min-w-0 space-y-3 overflow-hidden px-4 py-3 text-sm leading-6",
          isCandidateDeck
            ? "w-full max-w-none overflow-visible bg-transparent p-0"
            : isStructured
              ? "w-full max-w-[min(100%,40rem)]"
              : "w-fit max-w-[min(100%,36rem)]",
          isUser
            ? "rounded-3xl rounded-br-md bg-user text-white"
            : isCandidateDeck
              ? "rounded-none border-0"
              : "rounded-3xl rounded-bl-md border border-line bg-surface text-ink"
        )}
      >
        {contactCard && !isUser ? (
          <ContactCard
            payload={contactCard}
            connecting={actions.connectingMatchId === contactCard.match_id}
            connected={actions.connectedMatchIds.has(contactCard.match_id)}
            onConnect={() => actions.onConnect(contactCard.match_id)}
            onOpenChat={() => actions.onOpenChat?.(contactCard.match_id)}
          />
        ) : null}
        {requestCard && !isUser ? (
          <AttachmentRequestCard
            payload={requestCard}
            uploading={actions.uploadingRequestId === requestCard.request_id}
            onUpload={(files) =>
              actions.onRequestUpload(requestCard.request_id, files)
            }
          />
        ) : null}
        {permissionCard && !isUser ? (
          <AttachmentPermissionCard
            payload={permissionCard}
            busy={actions.grantingAttachmentId === permissionCard.attachment_id}
            onGrant={(granted) =>
              actions.onGrant(
                permissionCard.attachment_id,
                permissionCard.match_id,
                granted
              )
            }
          />
        ) : null}
        {shareCard && !isUser ? (
          <AttachmentShareCard
            payload={shareCard}
            attachments={attachments}
            accessToken={actions.accessToken}
          />
        ) : null}
        {candidateDeck && !isUser ? (
          <CandidateDeck
            payload={candidateDeck}
            accessToken={actions.accessToken}
            busyId={actions.suggestingId}
            onInterested={(suggestionId) =>
              actions.onSuggestion(suggestionId, "interested")
            }
            onSkip={(suggestionId) => actions.onSuggestion(suggestionId, "skip")}
            onRequestPhoto={(suggestionId, attachmentId) =>
              actions.onSuggestion(suggestionId, "interested", attachmentId)
            }
          />
        ) : null}
        {!hidePlainText && message.content ? (
          <div className="max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere] [word-break:break-word]">
            <ChatText text={message.content} />
          </div>
        ) : null}
        {attachments.length > 0 && !shareCard ? (
          <AttachmentStack
            attachments={attachments}
            inverted={isUser}
            accessToken={actions.accessToken}
          />
        ) : null}
      </div>
    </div>
  )
}
