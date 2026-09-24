"use client"

import { useEffect, useState } from "react"

import { getBrokerBackendUrl } from "@/lib/api/broker"

export function resolveAttachmentHref(
  contentUrl: string | null | undefined
): string | null {
  if (!contentUrl) return null
  if (
    contentUrl.startsWith("blob:") ||
    contentUrl.startsWith("http://") ||
    contentUrl.startsWith("https://")
  ) {
    return contentUrl
  }
  if (contentUrl.startsWith("/")) {
    return `${getBrokerBackendUrl()}${contentUrl}`
  }
  return contentUrl
}

export function useAuthObjectUrl(
  contentUrl: string | null | undefined,
  accessToken: string | null | undefined,
  enabled = true
): string | null {
  const [src, setSrc] = useState<string | null>(() =>
    contentUrl?.startsWith("blob:") ? contentUrl : null
  )

  useEffect(() => {
    if (!enabled) {
      setSrc(null)
      return
    }
    if (!contentUrl) {
      setSrc(null)
      return
    }
    if (contentUrl.startsWith("blob:")) {
      setSrc(contentUrl)
      return
    }

    const href = resolveAttachmentHref(contentUrl)
    if (!href) {
      setSrc(null)
      return
    }
    if (!accessToken || !contentUrl.startsWith("/")) {
      setSrc(href)
      return
    }

    let blobUrl: string | null = null
    let cancelled = false
    fetch(href, {
      headers: { Authorization: `Bearer ${accessToken}` }
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Download failed (${response.status})`)
        return response.blob()
      })
      .then((blob) => {
        blobUrl = URL.createObjectURL(blob)
        if (!cancelled) setSrc(blobUrl)
      })
      .catch(() => {
        if (!cancelled) setSrc(null)
      })

    return () => {
      cancelled = true
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [contentUrl, accessToken, enabled])

  return src
}
