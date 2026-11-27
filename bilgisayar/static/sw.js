/* Service worker: arayüz kabuğunu önbellekler (çevrimdışı açılış), API'yi asla önbelleklemez, Web Push gösterir. */
const SURUM = "vt-4";
const KABUK = ["/", "/static/stil.css", "/static/tema.js", "/static/uygulama.js", "/static/lib/lightweight-charts.standalone.production.js",
  "/static/ikon.svg", "/static/ikon-192.png", "/static/ikon-512.png", "/manifest.json"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SURUM).then((c) => c.addAll(KABUK))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((x) => x !== SURUM).map((x) => caches.delete(x)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return; // canlı veri: ağ
  // ağ öncelikli, olmazsa önbellek (güncellemeler hemen gelsin)
  e.respondWith(fetch(e.request).then((r) => { const k = r.clone(); caches.open(SURUM).then((c) => c.put(e.request, k)); return r; })
    .catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});
self.addEventListener("push", (e) => {
  let v = { baslik: "Borsa Veri Analisti", metin: "" };
  try { v = e.data.json(); } catch { /* düz metin */ }
  e.waitUntil(self.registration.showNotification(v.baslik, { body: v.metin, icon: "/static/ikon-192.png", badge: "/static/ikon-192.png" }));
});
self.addEventListener("notificationclick", (e) => { e.notification.close(); e.waitUntil(clients.openWindow("/#/sinyaller")); });
