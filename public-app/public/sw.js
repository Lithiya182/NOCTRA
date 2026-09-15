self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => self.clients.claim());

self.addEventListener("push", (event) => {
  let data = { title: "ThermalGuard alert", body: "A new fire alert was issued." };
  try { data = event.data ? event.data.json() : data; } catch (_) {}
  event.waitUntil(
    self.registration.showNotification(data.title || "ThermalGuard alert", {
      body: data.body || "A new fire alert was issued.",
      icon: "/thermalguard-icon.svg",
      badge: "/thermalguard-icon.svg",
      tag: "thermalguard-" + Date.now(),
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow("http://localhost:5174"));
});