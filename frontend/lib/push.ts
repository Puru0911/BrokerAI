import { getPushPublicKey, subscribePush } from "@/lib/api/broker"

export function pushSupported() {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window &&
    window.isSecureContext
  )
}

export function notificationPermission(): NotificationPermission | "unsupported" {
  if (!pushSupported()) return "unsupported"
  return Notification.permission
}

export async function requestNotificationPermission(): Promise<
  NotificationPermission | "unsupported"
> {
  if (!pushSupported()) return "unsupported"
  if (Notification.permission !== "default") return Notification.permission
  return Notification.requestPermission()
}

function urlBase64ToUint8Array(value: string) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4)
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/")
  const raw = window.atob(base64)
  const output = new Uint8Array(raw.length)
  for (let index = 0; index < raw.length; index += 1) {
    output[index] = raw.charCodeAt(index)
  }
  return output
}

function bufferToBase64Url(buffer: ArrayBuffer | null) {
  if (!buffer) return ""
  const bytes = new Uint8Array(buffer)
  let binary = ""
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return window
    .btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "")
}

export async function enablePushNotifications(accessToken: string) {
  if (!pushSupported()) return false
  if (Notification.permission !== "granted") return false

  const registration = await navigator.serviceWorker.register("/sw.js")
  await navigator.serviceWorker.ready

  let publicKey: string
  try {
    publicKey = (await getPushPublicKey(accessToken)).public_key
  } catch {
    return false
  }

  const existing = await registration.pushManager.getSubscription()
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey)
    }))

  const json = subscription.toJSON()
  const p256dh = json.keys?.p256dh || bufferToBase64Url(subscription.getKey("p256dh"))
  const auth = json.keys?.auth || bufferToBase64Url(subscription.getKey("auth"))
  if (!json.endpoint || !p256dh || !auth) return false

  await subscribePush(accessToken, {
    endpoint: json.endpoint,
    keys: { p256dh, auth },
    user_agent: navigator.userAgent.slice(0, 255)
  })
  return true
}
