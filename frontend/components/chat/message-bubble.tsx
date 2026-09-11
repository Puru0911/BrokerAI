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
import { ContactCard, parseContactCard } from "@/components/chat/contact-card"
import { cn } from "@/lib/cn"
import type { BrokerMessage } from "@/lib/api/broker"

export type MessageActions = {
  connectingMatchId: string | null
  connectedMatchIds: Set<string>
  onConnect: (matchId: string) => void
  onOpenChat?: (matchId: string) => void
  uploadingRequestId: string | null
  onRequestUpload: (requestId: string, file: File) => void
  grantingAttachmentId: string | null
  onGrant: (attachmentId: string, matchId: string, granted: boolean) => void
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
  const attachments = message.attachments || []
  const hidePlainText = Boolean(
    contactCard || requestCard || permissionCard || shareCard
  )
  const isStructured = hidePlainText

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "min-w-0 space-y-3 px-4 py-3 text-sm leading-6",
          isStructured
            ? "w-full max-w-[min(92%,40rem)]"
            : "max-w-[min(82%,36rem)]",
          isUser
            ? "rounded-3xl rounded-br-md bg-user text-white"
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
            onUpload={(file) =>
              actions.onRequestUpload(requestCard.request_id, file)
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
          <AttachmentShareCard payload={shareCard} attachments={attachments} />
        ) : null}
        {!hidePlainText && message.content ? (
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {message.content}
          </div>
        ) : null}
        {attachments.length && !shareCard ? (
          <AttachmentStack attachments={attachments} inverted={isUser} />
        ) : null}
      </div>
    </div>
  )
}
