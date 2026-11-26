/* Tarama (#/tarama) ve Analiz (#/analiz) ekranlarını ilk açılışta kurar. Telefon ve bilgisayar panosu ortak. */
import { ekranKur as taramaKur } from "./tarama.js";
import { ekranKur as analizKur, alarmIzle, alarmlar } from "./analiz.js";

const kurulu = {};
async function istatistikAl() {
  try { const r = await fetch(new URL("tarama_istatistik.json", import.meta.url), { cache: "no-cache" }); return r.ok ? r.json() : null; }
  catch { return null; }
}
async function kontrol() {
  const h = location.hash || "#/analiz";  // varsayılan ekran
  if (h.startsWith("#/tarama") && !kurulu.tarama && document.getElementById("taramaKok")) {
    kurulu.tarama = taramaKur(document.getElementById("taramaKok"), {});
    const ist = await istatistikAl();
    if (ist) kurulu.tarama.istatistik(ist);
  }
  if (h.startsWith("#/analiz") && !kurulu.analiz && document.getElementById("analizKok")) {
    kurulu.analiz = analizKur(document.getElementById("analizKok"));
  }
}
// Ortak kısa bildirim (her iki arayüzde #bildirim kutusu var)
document.addEventListener("analiz-bildirim", (e) => {
  const t = document.getElementById("bildirim");
  if (!t) return;
  t.textContent = e.detail; t.classList.remove("gizli");
  clearTimeout(t._z); t._z = setTimeout(() => t.classList.add("gizli"), 6000);
});
window.addEventListener("hashchange", kontrol);
kontrol();
if (alarmlar().some((x) => x.durum !== "teyit" && x.durum !== "iptal")) alarmIzle(); // bekleyen alarm varsa hangi sekmede olursa olsun izle
