import { getPushPublicKey, subscribePush } from "@/lib/api/broker"

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
  if (typeof window === "undefined") return
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return
  if (!window.isSecureContext) return

  const permission =
    Notification.permission === "default"
      ? await Notification.requestPermission()
      : Notification.permission
  if (permission !== "granted") return

  const registration = await navigator.serviceWorker.register("/sw.js")
  await navigator.serviceWorker.ready

  let publicKey: string
  try {
    publicKey = (await getPushPublicKey(accessToken)).public_key
  } catch {
    return
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
  if (!json.endpoint || !p256dh || !auth) return

  await subscribePush(accessToken, {
    endpoint: json.endpoint,
    keys: { p256dh, auth },
    user_agent: navigator.userAgent.slice(0, 255)
  })
}
