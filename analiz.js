/* Analiz ekranı (telefon ve bilgisayar panosu ortak): 1 saat / 4 saat / günlük sinyaller ayrı ayrı, 3 zaman dilimi teyitli
 * sinyaller, coin detayı (destek/direnç önerisi ve senaryolar) ve fiyat alarmları.
 * Veri: Binance spot (herkese açık, anahtarsız). Emir YOK. Her sinyalin yanında geçmiş isabet (formasyon_istatistik.json,
 * vadeli/formasyon.py araştırması; DENEYLER.md §4-5).
 */
import { tara, spotAl, havuz, el } from "./tarama.js";
import * as F from "./formasyon.js";

const TF = { "3d": { ad: "3 Günlük", ms: 3 * 86400e3, limit: 300, ofs: 86400e3 },
  "1w": { ad: "Haftalık", ms: 7 * 86400e3, limit: 300, ofs: 4 * 86400e3 }, "4h": { ad: "4 Saat", ms: 4 * 3600e3, limit: 300 },
  "1d": { ad: "Günlük", ms: 86400e3, limit: 300 } };
const MALIYET = 0.0015;
// İki bölüm (kullanıcı isteği): 4 saat · günlük ve 3 gün · haftalık; her birinde "teyitli" = küçük TF sinyali + büyük TF trendi
const TEYIT = { "4h": "1d", "3d": "1w" };
const BOLUM = {
  kisa: { sekmeler: [["1d", "Günlük"], ["4h", "4 Saat"], ["t4h", "4s + Günlük teyitli"]] },
  uzun: { sekmeler: [["1w", "Haftalık"], ["3d", "3 Günlük"], ["t3d", "3g + Haftalık teyitli"]] },
};
const SEKMELER = ["1d", "4h", "t4h", "1w", "3d", "t3d", "alarm"];
const teyitli = (s) => s.startsWith("t");
const kucuk = (s) => (teyitli(s) ? s.slice(1) : s);
const ALARM_ANAHTAR = "analiz:alarmlar";

// ------------------------------------------------------------------ biçim
const fiyatMetin = (x) => (x == null || !isFinite(x) ? "-" : x >= 1000 ? x.toLocaleString("tr-TR", { maximumFractionDigits: 2 })
  : x >= 1 ? String(+x.toPrecision(5)) : String(+x.toPrecision(4)));
const yuzde = (x, n = 1) => (x == null || !isFinite(x) ? "-" : (x > 0 ? "+" : "") + (x * 100).toFixed(n) + "%");
const oran = (x) => (x == null || !isFinite(x) ? "-" : "%" + Math.round(x * 100));
const usd = (x) => (x >= 1e9 ? (x / 1e9).toFixed(1) + "B" : x >= 1e6 ? (x / 1e6).toFixed(0) + "M" : (x / 1e3).toFixed(0) + "K");

// ------------------------------------------------------------------ veri
async function mumlar(sembol, tf) {
  const ham = await spotAl(`/api/v3/klines?symbol=${encodeURIComponent(sembol)}&interval=${tf}&limit=${TF[tf].limit}`);
  const simdi = Date.now(), k = ham.filter((x) => x[6] < simdi); // yalnız kapanmış mumlar
  return { t: k.map((x) => x[0]), o: k.map((x) => +x[1]), h: k.map((x) => +x[2]), l: k.map((x) => +x[3]), c: k.map((x) => +x[4]),
    v: k.map((x) => +x[7]) };
}

/** Son kapanmış mumdaki sinyaller + o zaman dilimindeki trend. */
function sonSinyaller(m) {
  const n = m.c.length;
  if (n < 120) return null;
  const S = F.sinyaller(m), i = n - 1, out = [];
  for (const [ad, [al, sat]] of Object.entries(S)) {
    if (al[i]) out.push({ ad, yon: 1 });
    if (sat[i]) out.push({ ad, yon: -1 });
  }
  return { sinyaller: out, trend: F.trend(m.c)[i], zaman: m.t[i] };
}

function hedefler(m, yon) {
  const i = m.c.length - 1, giris = m.c[i];
  const a = F.seviyeHedefi(m, i, yon, giris);
  if (!a) return null;
  const mesafe = F.STOP_ATR * a.atr;
  return { giris, atr: a.atr, stop: giris - yon * mesafe, h11: giris + yon * mesafe, h12: giris + yon * 2 * mesafe,
    sev_hedef: a.hedef, sev_stop: a.stop };
}

// ------------------------------------------------------------------ istatistik
let IST = null;
async function istatistikYukle() {
  if (IST) return IST;
  try { const r = await fetch(new URL("formasyon_istatistik.json", import.meta.url), { cache: "no-cache" }); IST = r.ok ? await r.json() : null; }
  catch { IST = null; }
  return IST;
}
function ist(ad, tf, yon, k) {
  if (!IST) return null;
  const x = IST.s[`${ad}|${tf}|${yon === 1 ? "long" : "short"}|${k}`];
  if (!x) return null;
  const [n, isabet, rastgele, ort_r, isabet_h, dog, umut] = x;
  return { n, isabet, rastgele, ort_r, isabet_h, dogrulanmis: !!dog, umut: !!umut };
}

// ------------------------------------------------------------------ tarama
const ONB = {}; // tf -> {kapanis, sonuc}
async function tfTara(semboller, tf, ilerleme, zorla) {
  const kapanis = Math.floor((Date.now() - (TF[tf].ofs || 0)) / TF[tf].ms); // Binance hizası: 3g 1970-01-02, hafta Pazartesi
  const k = `analiz:${tf}`;
  if (!zorla) {
    if (ONB[tf] && ONB[tf].kapanis === kapanis && ONB[tf].n === semboller.length) return ONB[tf].sonuc;
    try { const o = JSON.parse(sessionStorage.getItem(k) || "null"); if (o && o.kapanis === kapanis && o.n === semboller.length) { ONB[tf] = o; return o.sonuc; } }
    catch { /* yok */ }
  }
  const sonuc = {};
  await havuz(semboller, 8, async (s) => {
    const m = await mumlar(s, tf);
    const x = sonSinyaller(m);
    if (x) sonuc[s] = { ...x, hedef_l: x.sinyaller.some((y) => y.yon === 1) ? hedefler(m, 1) : null,
      hedef_s: x.sinyaller.some((y) => y.yon === -1) ? hedefler(m, -1) : null };
  }, ilerleme);
  ONB[tf] = { kapanis, n: semboller.length, sonuc };
  try { sessionStorage.setItem(k, JSON.stringify(ONB[tf])); } catch { /* dolu */ }
  return sonuc;
}

// ------------------------------------------------------------------ alarmlar
export function alarmlar() { try { return JSON.parse(localStorage.getItem(ALARM_ANAHTAR) || "[]"); } catch { return []; } }
function alarmKaydet(a) { try { localStorage.setItem(ALARM_ANAHTAR, JSON.stringify(a)); } catch { /* yok */ } }
export function alarmEkle({ sembol, seviye, yon, tf = "4h", not = "" }) {
  const a = alarmlar();
  a.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), sembol, seviye: +seviye, yon, tf, not,
    durum: "bekliyor", olusturma: Date.now(), olaylar: [] });
  alarmKaydet(a);
}

function bildir(baslik, metin) {
  try { if (navigator.vibrate) navigator.vibrate([200, 100, 200]); } catch { /* yok */ }
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      navigator.serviceWorker?.getRegistration?.().then((r) => (r ? r.showNotification(baslik, { body: metin, tag: baslik })
        : new Notification(baslik, { body: metin })));
    }
  } catch { /* yok */ }
  document.dispatchEvent(new CustomEvent("analiz-bildirim", { detail: `${baslik}: ${metin}` }));
}

/** Uygulama açıkken 30 sn'de bir: yaklaştı (%1) → anlık geçti → mum kapanışıyla teyit. */
let alarmZamanlayici = null;
export async function alarmKontrol() {
    const a = alarmlar().filter((x) => x.durum !== "teyit" && x.durum !== "iptal");
    if (!a.length) return;
    let fiyatlar;
    try { fiyatlar = new Map((await spotAl("/api/v3/ticker/price")).map((x) => [x.symbol, +x.price])); } catch { return; }
    const tum = alarmlar();
    for (const x of tum) {
      if (x.durum === "teyit" || x.durum === "iptal") continue;
      const p = fiyatlar.get(x.sembol);
      if (!p) continue;
      const yukari = x.yon === "yukari", gecti = yukari ? p > x.seviye : p < x.seviye;
      const yakin = Math.abs(p / x.seviye - 1) <= 0.01;
      const ad = x.sembol.replace(/USDT$/, "");
      if (x.durum === "bekliyor" && yakin && !gecti) {
        x.durum = "yaklasti"; x.olaylar.push([Date.now(), "yaklaştı", p]);
        bildir(`${ad} seviyeye yaklaştı`, `Fiyat ${fiyatMetin(p)}, seviye ${fiyatMetin(x.seviye)} (%1 içinde)`);
      }
      if ((x.durum === "bekliyor" || x.durum === "yaklasti") && gecti) {
        x.durum = "gecti"; x.olaylar.push([Date.now(), "anlık geçti", p]);
        bildir(`${ad} ${yukari ? "direnci geçti ↑" : "desteğin altına indi ↓"}`,
          `Fiyat ${fiyatMetin(p)} · seviye ${fiyatMetin(x.seviye)}. Henüz mum kapanışıyla teyit yok (${TF[x.tf].ad}).`);
      }
      if (x.durum === "gecti") {
        try {
          const m = await mumlar(x.sembol, x.tf);
          const n = m.c.length, son = m.c[n - 1], zaman = m.t[n - 1] + TF[x.tf].ms;
          const ilkOlay = [...x.olaylar].reverse().find((e) => e[1] === "anlık geçti"); // EN SON geçiş
          if (ilkOlay && zaman > ilkOlay[0]) {  // yalnız kırılımdan SONRA kapanan mum teyit edebilir
            if (yukari ? son > x.seviye : son < x.seviye) {
              x.durum = "teyit"; x.olaylar.push([Date.now(), "kapanışla teyit", son]);
              bildir(`${ad} kırılım TEYİT ✓`, `${TF[x.tf].ad} mum ${fiyatMetin(son)} ile seviyenin ${yukari ? "üstünde" : "altında"} kapandı.`);
            } else {
              x.durum = "bekliyor"; x.olaylar.push([Date.now(), "sahte kırılım: mum geri kapandı", son]);
              bildir(`${ad} sahte kırılım`, `${TF[x.tf].ad} mum seviyenin ${yukari ? "altında" : "üstünde"} kapandı (${fiyatMetin(son)}). Alarm yeniden beklemede.`);
            }
          }
        } catch { /* sonraki tur */ }
      }
    }
    alarmKaydet(tum);
    document.dispatchEvent(new CustomEvent("analiz-alarm"));
}
export function alarmIzle() {
  if (alarmZamanlayici) return;
  alarmKontrol();
  alarmZamanlayici = setInterval(alarmKontrol, 30e3);
}

// ------------------------------------------------------------------ arayüz
const YON_AD = { 1: "AL", "-1": "SAT" };
export function ekranKur(kok) {
  const d = { sekme: "1d", bolum: "kisa", yon: "", dogrulanmis: "", minHacim: 1e7, pazar: "", veri: {}, evren: null, detay: null, ...oku() };
  const durum = el("p", { class: "soluk" });
  const icerik = el("div");
  const sekBtn = (k, t) => el("button", { "data-s": k, onclick: () => { d.sekme = k; d.detay = null; yaz(d); yukle(); } }, t);
  const bolBtn = (k, t) => el("button", { "data-b": k, onclick: () => { d.bolum = k; d.sekme = k === "alarm" ? "alarm" : BOLUM[k].sekmeler[0][0];
    d.detay = null; yaz(d); yukle(); } }, t);
  const bolumler = el("div", { class: "bolumler" }, bolBtn("kisa", "4 Saat · Günlük"), bolBtn("uzun", "3 Gün · Haftalık"), bolBtn("alarm", "🔔 Alarmlar"));
  const sekmeler = el("div", { class: "altsekme analiz-sekme" });
  const yonSec = el("select", { "aria-label": "Yön", onchange: (e) => { d.yon = e.target.value; yaz(d); ciz(); } },
    el("option", { value: "" }, "Al + Sat"), el("option", { value: "1" }, "Yalnız AL"), el("option", { value: "-1" }, "Yalnız SAT"));
  const dogSec = el("select", { "aria-label": "Güven", onchange: (e) => { d.dogrulanmis = e.target.value; yaz(d); ciz(); } },
    el("option", { value: "" }, "Tüm sinyaller"), el("option", { value: "umut" }, "★ doğrulanmış + ◆ umut verici"),
    el("option", { value: "dog" }, "Yalnız ★ doğrulanmış"));
  const hacSec = el("select", { "aria-label": "Minimum hacim", onchange: (e) => { d.minHacim = +e.target.value; yaz(d); d.veri = {}; yukle(); } },
    [[1e6, "Hacim ≥ 1M $"], [1e7, "≥ 10M $"], [5e7, "≥ 50M $"], [0, "Hepsi"]].map(([v, t]) => el("option", { value: v }, t)));
  const pazarSec = el("select", { "aria-label": "Piyasa", onchange: (e) => { d.pazar = e.target.value; yaz(d); ciz(); } },
    el("option", { value: "" }, "Spot + vadeli"), el("option", { value: "vadeli" }, "Vadelide olanlar"), el("option", { value: "spot" }, "Yalnız spot"));
  const filtre = el("div", { class: "filtre" }, yonSec, hacSec, pazarSec, dogSec,
    el("button", { class: "kucuk ikincil", onclick: () => { d.veri = {}; yukle(true); } }, "↻"));
  kok.replaceChildren(bolumler, sekmeler, filtre, durum, icerik);
  document.addEventListener("analiz-alarm", () => { if (d.sekme === "alarm") ciz(); });

  async function evren() {
    if (!d.evren) d.evren = await tara({});
    return d.evren.satirlar.filter((x) => x.tur === "kripto" && x.hacim24 >= d.minHacim);
  }

  async function yukle(zorla = false) {
    ciz();
    if (d.sekme === "alarm") return;
    await istatistikYukle();
    try {
      durum.textContent = "Coin listesi alınıyor…";
      const ev = await evren();
      const semboller = ev.map((x) => x.sembol);
      const tfler = teyitli(d.sekme) ? [TEYIT[kucuk(d.sekme)], kucuk(d.sekme)] : [d.sekme];
      for (const tf of tfler) {
        if (d.veri[tf] && !zorla) continue;
        d.veri[tf] = await tfTara(semboller, tf, (i, n) => { if (i % 10 === 0 || i === n) durum.textContent = `${TF[tf].ad}: ${i}/${n} coin taranıyor…`; }, zorla);
      }
      ciz();
    } catch (e) { durum.textContent = "Veri alınamadı: " + e.message; }
  }

  function satirlar() {
    const ev = new Map((d.evren?.satirlar || []).map((x) => [x.sembol, x]));
    const out = [];
    const tfAd = kucuk(d.sekme);
    const v = d.veri[tfAd];
    if (!v) return out;
    for (const [s, x] of Object.entries(v)) {
      const meta = ev.get(s) || {};
      if (d.pazar && (d.pazar === "vadeli" ? !meta.vadeli : meta.vadeli)) continue;
      for (const sg of x.sinyaller) {
        if (d.yon && String(sg.yon) !== d.yon) continue;
        let anahtar = sg.ad, tf = tfAd;
        if (teyitli(d.sekme)) {   // küçük zaman dilimi sinyali + kendi ve büyük zaman dilimi trendi aynı yönde (DENEYLER.md §6-7)
          const t1 = d.veri[TEYIT[tfAd]]?.[s]?.trend;
          if (!(x.trend === sg.yon && t1 === sg.yon)) continue;
          anahtar = sg.ad + "+2tf";
        }
        const st = { "1:1": ist(anahtar, tf, sg.yon, "1:1"), "1:2": ist(anahtar, tf, sg.yon, "1:2"), seviye: ist(anahtar, tf, sg.yon, "seviye") };
        const dog = Object.values(st).some((y) => y && y.dogrulanmis);
        const umut = !dog && Object.values(st).some((y) => y && y.umut);
        if (d.dogrulanmis === "dog" && !dog) continue;
        if (d.dogrulanmis === "umut" && !dog && !umut) continue;
        out.push({ sembol: s, meta, ...sg, st, dog, umut, tf, zaman: x.zaman, hedef: sg.yon === 1 ? x.hedef_l : x.hedef_s });
      }
    }
    out.sort((a, b) => (b.dog - a.dog) || (b.umut - a.umut) || ((b.st["1:1"]?.isabet ?? 0) - (a.st["1:1"]?.isabet ?? 0)) || (b.meta.hacim24 || 0) - (a.meta.hacim24 || 0));
    return out;
  }

  function sinyalKarti(x) {
    const h = x.hedef, sat = x.yon === -1;
    const st = (k, etiket) => {
      const y = x.st[k];
      return el("div", { class: "isabet" + (y && y.dogrulanmis ? " dog" : y && y.umut ? " umut" : "") }, el("span", {}, etiket),
        el("b", {}, y ? oran(y.isabet) : "-"), el("i", {}, y ? `rastgele ${oran(y.rastgele)} · ${y.n} olay` : "veri yok"));
    };
    const kopyala = (t, v) => el("button", { class: "kopya", onclick: async (e) => { e.stopPropagation();
      try { await navigator.clipboard.writeText(String(v)); } catch { /* yok */ } } }, t);
    return el("div", { class: `kart sinyal-k ${sat ? "sat" : "al"}`, onclick: () => { d.detay = x.sembol; ciz(); } },
      el("div", { class: "ust-satir" },
        el("div", {}, el("span", { class: "yon-rozet " + (sat ? "sat" : "al") }, YON_AD[x.yon]), " ",
          el("b", { class: "coin-ad" }, x.sembol.replace(/USDT$/, "")), x.meta.vadeli ? el("i", { class: "rozet-v" }, "V") : null),
        x.dog ? el("span", { class: "yildiz", title: "Geçmiş testte kuralları geçti" }, "★ doğrulanmış")
          : x.umut ? el("span", { class: "umut-rozet", title: "Bütün testleri geçti ama geçmişte 300'den az kez görüldü: umut verici, kesin değil" }, "◆ umut verici · az olay") : null),
      el("div", { class: "form-ad" }, F.AD[x.ad], el("span", { class: "soluk" }, ` · ${TF[x.tf].ad}${teyitli(d.sekme) ? ` · ${TF[TEYIT[x.tf]].ad.toLowerCase()} trend teyitli` : ""}`)),
      el("div", { class: "isabetler" }, st("1:1", "Yakın hedef"), st("1:2", "Uzak hedef"), st("seviye", "Seviye hedefi")),
      h ? el("div", { class: "fiyatlar" },
        el("div", {}, el("span", {}, "Giriş ~"), el("b", {}, fiyatMetin(h.giris))),
        el("div", {}, el("span", {}, "Stop"), el("b", { class: "negatif" }, fiyatMetin(h.stop)), el("i", {}, yuzde(h.stop / h.giris - 1))),
        el("div", {}, el("span", {}, "Hedef 1:1"), el("b", { class: "pozitif" }, fiyatMetin(h.h11)), el("i", {}, yuzde(h.h11 / h.giris - 1))),
        el("div", {}, el("span", {}, "Hedef 1:2"), el("b", { class: "pozitif" }, fiyatMetin(h.h12)), el("i", {}, yuzde(h.h12 / h.giris - 1))),
        h.sev_hedef ? el("div", {}, el("span", {}, sat ? "Sonraki destek" : "Sonraki direnç"), el("b", { class: "pozitif" }, fiyatMetin(h.sev_hedef)),
          el("i", {}, `stop ${fiyatMetin(h.sev_stop)}`)) : null) : null,
      h && Math.abs(h.stop / h.giris - 1) > 0.25 ? el("p", { class: "uyari-kutu" }, `Stop çok uzak (${yuzde(Math.abs(h.stop / h.giris - 1), 0).replace("+", "")}). `,
        "Aynı riski almak için pozisyonu küçük tut (ör. hesabının %1'ini riske edeceksen pozisyon = hesap × %1 ÷ stop mesafesi); kaldıraç kullanma.") : null,
      el("p", { class: "not" }, sat ? "Vadeli: short · Spot: elinde varsa sat, yoksa alma." : "Spot veya vadeli: al. Stop'u borsaya hemen gir.",
        " Giriş fiyatı son kapanıştır; gerçek giriş sonraki mumun açılışı."));
  }

  function ciz() {
    $$("button", bolumler).forEach((b) => b.classList.toggle("secili", b.dataset.b === d.bolum));
    sekmeler.replaceChildren(...(d.bolum === "alarm" ? [] : BOLUM[d.bolum].sekmeler.map(([k, t]) => sekBtn(k, t))));
    $$("button", sekmeler).forEach((b) => b.classList.toggle("secili", b.dataset.s === d.sekme));
    yonSec.value = d.yon; hacSec.value = String(d.minHacim); pazarSec.value = d.pazar; dogSec.value = d.dogrulanmis;
    filtre.classList.toggle("gizli", d.sekme === "alarm" || !!d.detay);
    if (d.detay) return detayCiz(d.detay);
    if (d.sekme === "alarm") { durum.textContent = ""; return alarmCiz(); }
    const s = satirlar();
    const tfAd = kucuk(d.sekme);
    if (!d.veri[tfAd]) { icerik.replaceChildren(); return; }
    const z = Object.values(d.veri[tfAd])[0]?.zaman;
    durum.textContent = `${Object.keys(d.veri[tfAd]).length} coin · ${s.length} sinyal` + (z ? ` · son kapanan ${TF[tfAd].ad.toLowerCase()} mum: ${new Date(z + TF[tfAd].ms).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : "");
    const bilgi = el("details", { class: "bilgi" }, el("summary", {}, "Bu oranlar ne demek?"),
      el("p", {}, "Her oran, bu sinyal geçmişte (181 coin; 4s·günlük 2021-2026, 3g·haftalık 2019-2026) çıktığında fiyatın stoptan önce hedefe ulaşma oranıdır. ",
        "Yakın hedef = stop kadar uzak (1:1), uzak hedef = stopun 2 katı (1:2), seviye hedefi = sonraki direnç/destek. ",
        "\"Rastgele\" aynı kurallarla rastgele girişin oranıdır: sinyal ancak rastgeleden yüksekse işe yarar. ",
        "★ doğrulanmış = önceden yazılmış sıkı testi geçti (yeterli olay, anlamlı fark, son iki yılda da tuttu, maliyet sonrası kâr). ",
        "◆ umut verici = aynı testleri geçti ama geçmişte yalnız 100-299 kez görüldü; daha az güvenilir. ",
        "%80'e ulaşan tek sinyal haftalık RSI 30 dönüşü AL (◆, 270 olay); geri kalanların en iyileri %55-67."));
    icerik.replaceChildren(bilgi, s.length ? el("div", { class: "kartlar" }, s.slice(0, 120).map(sinyalKarti))
      : el("p", { class: "soluk" }, teyitli(d.sekme) ? `Şu an ${TF[TEYIT[tfAd]].ad.toLowerCase()} trendle teyitli ${TF[tfAd].ad.toLowerCase()} sinyal yok.` : "Bu mumda sinyal yok."));
  }

  async function detayCiz(sembol) {
    const ad = sembol.replace(/USDT$/, "");
    icerik.replaceChildren(el("button", { class: "kucuk ikincil", onclick: () => { d.detay = null; ciz(); } }, "← Listeye dön"),
      el("p", { class: "soluk" }, `${ad} destek/direnç seviyeleri hesaplanıyor…`));
    durum.textContent = "";
    await istatistikYukle();
    const bloklar = [];
    for (const tf of d.bolum === "uzun" ? ["1w", "3d"] : ["1d", "4h"]) {
      let m;
      try { m = await mumlar(sembol, tf); } catch { continue; }
      const sv = F.seviyeler(m, 3);
      if (!sv.fiyat) continue;
      const kir = (yon) => ist("dd_kirilim", tf, yon, "seviye");
      const ki = kir(1), ka = kir(-1);
      const seviyeSatir = (s, tur) => el("div", { class: "seviye " + tur },
        el("div", {}, el("b", {}, fiyatMetin(s.fiyat)), el("i", {}, `${yuzde(s.uzaklik)} · ${s.dokunma} dokunuş`)),
        el("button", { class: "kucuk ikincil", onclick: () => { alarmEkle({ sembol, seviye: s.fiyat, yon: tur === "direnc" ? "yukari" : "asagi", tf,
          not: `${TF[tf].ad} ${tur === "direnc" ? "direnç" : "destek"}` }); alarmIzle(); bildirMetin(`🔔 Alarm kuruldu: ${ad} ${fiyatMetin(s.fiyat)}`); } }, "🔔 Alarm"));
      const r1 = sv.direncler[0], r2 = sv.direncler[1], s1 = sv.destekler[0], s2 = sv.destekler[1];
      const senaryo = [];
      if (r1) senaryo.push(el("li", {}, el("b", { class: "pozitif" }, `${fiyatMetin(r1.fiyat)} direncini `), `${TF[tf].ad.toLowerCase()} kapanışla kırarsa → `,
        r2 ? `sonraki direnç ${fiyatMetin(r2.fiyat)} (${yuzde(r2.fiyat / sv.fiyat - 1)})` : "üstünde yakın direnç yok",
        ki ? el("i", {}, ` · geçmişte bu tür kırılımlarda sonraki dirence ulaşma ${oran(ki.isabet)} (rastgele ${oran(ki.rastgele)})`) : null));
      if (s1) senaryo.push(el("li", {}, el("b", { class: "negatif" }, `${fiyatMetin(s1.fiyat)} desteğini `), `${TF[tf].ad.toLowerCase()} kapanışla kırarsa → `,
        s2 ? `sonraki destek ${fiyatMetin(s2.fiyat)} (${yuzde(s2.fiyat / sv.fiyat - 1)})` : "altında yakın destek yok",
        ka ? el("i", {}, ` · geçmişte sonraki desteğe ulaşma ${oran(ka.isabet)} (rastgele ${oran(ka.rastgele)})`) : null));
      bloklar.push(el("div", { class: "kart" }, el("h3", {}, `${TF[tf].ad} grafik`), el("p", { class: "soluk" }, `Son kapanış ${fiyatMetin(sv.fiyat)}`),
        el("div", { class: "seviye-izgara" },
          el("div", {}, el("h4", {}, "Dirençler ↑"), sv.direncler.length ? sv.direncler.map((s) => seviyeSatir(s, "direnc")) : el("p", { class: "soluk" }, "Yakında yok")),
          el("div", {}, el("h4", {}, "Destekler ↓"), sv.destekler.length ? sv.destekler.map((s) => seviyeSatir(s, "destek")) : el("p", { class: "soluk" }, "Yakında yok"))),
        senaryo.length ? el("ul", { class: "senaryo" }, senaryo) : null));
    }
    icerik.replaceChildren(el("button", { class: "kucuk ikincil", onclick: () => { d.detay = null; ciz(); } }, "← Listeye dön"),
      el("h2", {}, ad), ...bloklar, ozelAlarmFormu(sembol),
      el("p", { class: "not" }, "Seviyeler son 200 mumdaki onaylı tepe ve diplerden (sağında ve solunda 5 mum) hesaplanır; birbirine 0.5 ATR'den yakın olanlar birleştirilir. Dokunuş = o bölgede kaç tepe/dip olduğu."));
  }

  function ozelAlarmFormu(sembol) {
    const f = el("form", { class: "form kart", onsubmit: (e) => { e.preventDefault();
      const s = (f.sembol.value || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
      if (!s || !(+f.seviye.value > 0)) return;
      alarmEkle({ sembol: s.endsWith("USDT") ? s : s + "USDT", seviye: +f.seviye.value, yon: f.yon.value, tf: f.tf.value, not: "elle" });
      alarmIzle(); bildirMetin("🔔 Alarm kuruldu"); f.seviye.value = ""; if (d.sekme === "alarm") ciz(); } },
      el("h3", { class: "genis" }, "Kendi seviyeni gir (ör. fiyat 3 iken 4'ü geçince haber ver)"),
      el("label", {}, "Coin", el("input", { name: "sembol", value: sembol ? sembol.replace(/USDT$/, "") : "", placeholder: "BTC", maxlength: 20, required: true })),
      el("label", {}, "Seviye", el("input", { name: "seviye", type: "number", step: "any", min: "0", required: true })),
      el("label", {}, "Yön", el("select", { name: "yon" }, el("option", { value: "yukari" }, "Yukarı geçince"), el("option", { value: "asagi" }, "Aşağı inince"))),
      el("label", {}, "Teyit mumu", el("select", { name: "tf" }, ["4h", "1d", "3d", "1w"].map((t) => el("option", { value: t }, TF[t].ad)))),
      el("button", { type: "submit" }, "Alarm kur"));
    return f;
  }

  function alarmCiz() {
    const a = alarmlar().slice().reverse();
    const izin = "Notification" in window && Notification.permission !== "granted"
      ? el("button", { class: "ikincil", onclick: async () => { try { await Notification.requestPermission(); } catch { /* yok */ } ciz(); } }, "Bildirimlere izin ver") : null;
    const DURUM = { bekliyor: "Bekliyor", yaklasti: "Yaklaştı (%1)", gecti: "Geçti · teyit bekleniyor", teyit: "TEYİT ✓", iptal: "İptal" };
    icerik.replaceChildren(
      el("p", { class: "uyari-kutu" }, "Alarmlar yalnızca uygulama (veya pano sekmesi) açıkken kontrol edilir (30 sn'de bir). ",
        "Üç aşama: seviyeye %1 kala, fiyat seviyeyi anlık geçince ve seçtiğin mum seviyenin ötesinde kapanınca (teyit). ",
        "Mum geri kapanırsa \"sahte kırılım\" der ve alarmı yeniden bekletir."), izin, ozelAlarmFormu(""),
      a.length ? el("div", { class: "kartlar" }, a.map((x) => el("div", { class: "kart alarm d-" + x.durum },
        el("div", { class: "ust-satir" }, el("b", { class: "coin-ad" }, x.sembol.replace(/USDT$/, "")), el("span", { class: "alarm-durum" }, DURUM[x.durum])),
        el("p", {}, `${x.yon === "yukari" ? "↑ Yukarı geçince" : "↓ Aşağı inince"}: ${fiyatMetin(x.seviye)} · teyit: ${TF[x.tf].ad} mum`,
          x.not ? el("span", { class: "soluk" }, ` · ${x.not}`) : null),
        x.olaylar.length ? el("ul", { class: "olaylar" }, x.olaylar.map(([t, o, p]) => el("li", {}, `${new Date(t).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} — ${o} (${fiyatMetin(p)})`))) : null,
        el("button", { class: "kucuk tehlike", onclick: () => { alarmKaydet(alarmlar().filter((y) => y.id !== x.id)); ciz(); } }, "Sil"))))
        : el("p", { class: "soluk" }, "Henüz alarm yok. Bir coinin detayından (sinyal kartına dokun) veya yukarıdaki formdan kurabilirsin."));
  }

  function bildirMetin(m) { document.dispatchEvent(new CustomEvent("analiz-bildirim", { detail: m })); }
  ciz();
  yukle();
  alarmIzle();
  return { yenile: () => { d.veri = {}; yukle(true); } };
}

const $$ = (s, k = document) => [...k.querySelectorAll(s)];
function oku() { try { const x = JSON.parse(localStorage.getItem("analiz:ayar") || "{}"); return { sekme: SEKMELER.includes(x.sekme) ? x.sekme : "1d",
  bolum: ["kisa", "uzun", "alarm"].includes(x.bolum) ? x.bolum : "kisa", yon: x.yon || "",
  dogrulanmis: ["", "umut", "dog"].includes(x.dogrulanmis) ? x.dogrulanmis : "", minHacim: x.minHacim ?? 1e7, pazar: x.pazar || "" }; } catch { return {}; } }
function yaz(d) { try { localStorage.setItem("analiz:ayar", JSON.stringify({ sekme: d.sekme, bolum: d.bolum, yon: d.yon, dogrulanmis: d.dogrulanmis,
  minHacim: d.minHacim, pazar: d.pazar })); } catch { /* yok */ } }
