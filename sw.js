/* Vadeli Tarayıcı (telefon) — yalnızca uygulama kabuğunu önbellekler; Binance verisini ASLA önbelleklemez. */
const SURUM = "vadeli-1";
const KABUK = ["./", "index.html", "stil.css?v=1", "uygulama.js?v=1", "strateji.js", "binance.js",
  "lib/lightweight-charts.standalone.production.js", "manifest.json", "ikon.svg", "ikon-192.png", "ikon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SURUM).then((c) => c.addAll(KABUK))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((x) => x.startsWith("vadeli-") && x !== SURUM).map((x) => caches.delete(x))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return; // Binance: her zaman ağdan
  // Ağ öncelikli (güncellemeler hemen gelsin), çevrimdışıysa önbellek
  e.respondWith(fetch(e.request).then((r) => { const k = r.clone(); caches.open(SURUM).then((c) => c.put(e.request, k)); return r; })
    .catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))));
});
self.addEventListener("notificationclick", (e) => { e.notification.close(); e.waitUntil(clients.openWindow("./#/sinyaller")); });
