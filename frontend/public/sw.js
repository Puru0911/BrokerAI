self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {}
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true
      })
      if (windows.some((client) => client.focused)) {
        return
      }
      const title = data.title || "BrokerAI"
      await self.registration.showNotification(title, {
        body: data.body || "New message",
        data: {
          url: data.url || "/app",
          connection_id: data.connection_id || null
        }
      })
    })()
  )
})

self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const target = event.notification.data?.url || "/app"
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true
      })
      for (const client of windows) {
        if ("focus" in client) {
          client.postMessage({
            type: "open-chat",
            url: target,
            connection_id: event.notification.data?.connection_id || null
          })
          await client.focus()
          return
        }
      }
      await self.clients.openWindow(target)
    })()
  )
})
