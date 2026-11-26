/* Piyasa taraması (Binance spot + vadeli, herkese açık veri; API anahtarı YOK, emir YOK).
 *
 * Telefon uygulaması (mobil/) ve bilgisayar panosu (static/, /static/tarama.js olarak sunulur) AYNI dosyayı kullanır.
 *  1) Son 3 ay / 6 ay / 1 yılda en çok düşen ve en çok yükselen 50 coin
 *  2) Hacme göre sıralama
 *  3) Hacim durumu: hacmi artan, aşırı artan (kısa vadede düşüş riski?), kurumuş (toparlanma?)
 * Ölçüler `vadeli/tarama.py` ile birebir aynı tanımlanır (geçmiş istatistikler oradan gelir: tarama_istatistik.json).
 */

const SPOT_TABANLAR = ["https://data-api.binance.vision", "https://api.binance.com"];
const VADELI_TABAN = "https://fapi.binance.com";
const ONBELLEK_ANAHTAR = "tarama:v2";
const ONBELLEK_SURE = 60 * 60 * 1000; // 1 saat
export const DONEMLER = { "3a": { ad: "3 ay", gun: 90 }, "6a": { ad: "6 ay", gun: 180 }, "1y": { ad: "1 yıl", gun: 365 } };

// Stabil coinler ve kaldıraçlı tokenler listelere girmez
const STABIL = new Set(["USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "EUR", "GBP", "AEUR", "USDE", "PAX", "SUSD", "UST",
  "XUSD", "BFUSD", "USD1", "RLUSD", "EURI", "PAXG", "WBTC", "WBETH", "BNSOL"]);
const kaldiracli = (b) => /(UP|DOWN|BULL|BEAR)$/.test(b) && b.length > 4;
// Binance spotundaki tokenize hisse/ETF'ler "B" ekiyle listelenir (NVDAB, TSLAB, SPYB…). Adı B ile biten gerçek kriptolar:
const KRIPTO_B = new Set(["BNB", "ARB", "SHIB", "TRB", "CKB", "BEB", "BB", "YB", "DGB", "WEB", "LAB", "SUB", "PUB", "CRB"]);
const EMTIA = new Set(["XAUT", "PAXG", "XAU", "XAG"]);
/** Varlık türü: kripto | hisse (tokenize hisse/ETF) | emtia | stabil (fiyatı 90 gün boyunca 1$ ±%3) */
export function varlikTuru(baz, kapanislar) {
  if (EMTIA.has(baz)) return "emtia";
  if (baz.endsWith("B") && baz.length >= 3 && !KRIPTO_B.has(baz)) return "hisse";
  const son = kapanislar.slice(-90);
  if (son.length >= 30 && son.every((c) => c > 0.97 && c < 1.03)) return "stabil";
  return "kripto";
}

// ------------------------------------------------------------------ veri
const bekle = (ms) => new Promise((r) => setTimeout(r, ms));

export async function spotAl(yol) {
  let son;
  for (const taban of SPOT_TABANLAR) {
    for (let i = 0; i < 3; i++) {
      try {
        const r = await fetch(taban + yol, { cache: "no-store" });
        if (r.ok) return r.json();
        if (r.status === 429 || r.status === 418) { await bekle((Number(r.headers.get("Retry-After")) || 10) * 1000); continue; }
        son = new Error(`Binance spot HTTP ${r.status}`);
        break; // bu tabanda kalıcı hata: diğer tabanı dene
      } catch (e) { son = e; await bekle(800 * (i + 1)); }
    }
  }
  throw son || new Error("Binance spot'a ulaşılamadı");
}

export async function havuz(liste, n, fn, ilerleme) {
  const out = new Array(liste.length);
  let i = 0, biten = 0;
  await Promise.all(Array.from({ length: Math.min(n, liste.length) }, async () => {
    while (i < liste.length) {
      const k = i++;
      try { out[k] = await fn(liste[k]); } catch { out[k] = null; }
      biten++; if (ilerleme) ilerleme(biten, liste.length);
    }
  }));
  return out;
}

/** Günlük mumlar: [[açılış_ms, o, h, l, c, hacim_usdt], ...] yalnız KAPANMIŞ günler. */
async function gunlukMumlar(sembol, limit = 400) {
  const ham = await spotAl(`/api/v3/klines?symbol=${encodeURIComponent(sembol)}&interval=1d&limit=${limit}`);
  const simdi = Date.now();
  return ham.filter((k) => k[6] < simdi).map((k) => [k[0], +k[1], +k[2], +k[3], +k[4], +k[7]]);
}

// ------------------------------------------------------------------ ölçüler (tarama.py ile aynı)
const ort = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN);

/** Kapanmış günlük mumlardan ölçüler. Son kapanış = dünün kapanışı (bugünkü kısmi gün kullanılmaz). */
export function olculer(m) {
  const n = m.length;
  if (n < 30) return null;
  const c = m.map((x) => x[4]), qv = m.map((x) => x[5]);
  const son = c[n - 1];
  const getiri = (g) => (n > g ? son / c[n - 1 - g] - 1 : null);
  const h7 = ort(qv.slice(-7)), h20 = ort(qv.slice(-21, -1)), h30 = ort(qv.slice(-30)), h90 = n >= 90 ? ort(qv.slice(-90)) : NaN;
  return {
    gun: n, kapanis: son,
    g90: getiri(90), g180: getiri(180), g365: getiri(365), g30: getiri(30), g7: getiri(7),
    hacim30: h30,
    hacim_egilim: h30 > 0 ? h7 / h30 : null,                  // son 7 gün / son 30 gün ortalama hacim
    hacim_patlama: h20 > 0 ? qv[n - 1] / h20 : null,          // dünkü hacim / önceki 20 gün ortalaması
    hacim_kuruma: h90 > 0 ? h7 / h90 : null,                  // son 7 gün / son 90 gün
    zirveden: son / Math.max(...c.slice(-365)) - 1,           // 1 yıllık zirveden uzaklık
  };
}

/** Hacim durumu sınıfları. Eşikler tarama_istatistik.json'dan (araştırma) gelir; yoksa varsayılan. */
export function hacimSiniflari(o, e = VARSAYILAN_ESIK) {
  const s = [];
  if (o.hacim_patlama != null && o.hacim_patlama >= e.patlama) s.push("patlama");
  if (o.hacim_egilim != null && o.hacim_egilim >= e.artan && !(o.hacim_patlama >= e.patlama)) s.push("artan");
  if (o.hacim_kuruma != null && o.hacim_kuruma <= e.kuruma) s.push("kuruma");
  return s;
}
export const VARSAYILAN_ESIK = { patlama: 3, artan: 1.5, kuruma: 0.4 };

// ------------------------------------------------------------------ tarama
export async function tara({ ilerleme, zorla = false } = {}) {
  if (!zorla) {
    try {
      const o = JSON.parse(localStorage.getItem(ONBELLEK_ANAHTAR) || "null");
      if (o && Date.now() - o.zaman < ONBELLEK_SURE) return o;
    } catch { /* yok */ }
  }
  const tick = await spotAl("/api/v3/ticker/24hr?type=FULL");
  let vadeli = new Set();
  try {
    const r = await fetch(VADELI_TABAN + "/fapi/v1/ticker/price", { cache: "no-store" });
    if (r.ok) vadeli = new Set((await r.json()).map((x) => x.symbol));
  } catch { /* vadeli erişilemezse işaretlenmez */ }
  const adaylar = tick.filter((t) => t.symbol.endsWith("USDT") && +t.quoteVolume > 0 && +t.count > 0)
    .map((t) => ({ sembol: t.symbol, baz: t.symbol.slice(0, -4), fiyat: +t.lastPrice, d24: +t.priceChangePercent / 100,
      hacim24: +t.quoteVolume }))
    .filter((t) => !STABIL.has(t.baz) && !kaldiracli(t.baz));
  const mumlar = await havuz(adaylar, 8, (a) => gunlukMumlar(a.sembol), ilerleme);
  const satirlar = [];
  adaylar.forEach((a, i) => {
    const m = mumlar[i];
    if (!m) return;
    const o = olculer(m);
    if (!o) return;
    const tur = varlikTuru(a.baz, m.map((x) => x[4]));
    if (tur === "stabil") return;
    satirlar.push({ ...a, ...o, tur, vadeli: vadeli.has(a.sembol) });
  });
  const sonuc = { zaman: Date.now(), satirlar, vadeli_bilgisi: vadeli.size > 0 };
  try { localStorage.setItem(ONBELLEK_ANAHTAR, JSON.stringify(sonuc)); } catch { /* dolu */ }
  return sonuc;
}

// ------------------------------------------------------------------ arayüz
export function el(etiket, oz = {}, ...cocuk) {
  const e = document.createElement(etiket);
  for (const [k, v] of Object.entries(oz || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of cocuk.flat()) if (c != null && c !== false) e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
const yuzde = (x, n = 1) => (x == null || !isFinite(x) ? "-" : (x > 0 ? "+" : "") + (x * 100).toFixed(n) + "%");
const usd = (x) => { if (x == null || !isFinite(x)) return "-"; const a = Math.abs(x);
  return a >= 1e9 ? (x / 1e9).toFixed(2) + "B" : a >= 1e6 ? (x / 1e6).toFixed(1) + "M" : a >= 1e3 ? (x / 1e3).toFixed(0) + "K" : x.toFixed(0); };
const fiyatMetin = (x) => (x >= 1000 ? x.toLocaleString("tr-TR", { maximumFractionDigits: 2 }) : x >= 1 ? x.toPrecision(5) : x.toPrecision(4));
const kat = (x) => (x == null || !isFinite(x) ? "-" : x.toFixed(1) + "×");

const SINIF_AD = { patlama: "Hacim patlaması", artan: "Hacmi artıyor", kuruma: "Hacmi kurumuş" };
const SINIF_ACIKLAMA = {
  patlama: "Dünkü hacim önceki 20 günün ortalamasının {e} katından fazla. Ani ilgi; kısa vadede sert geri dönüş riski de taşır.",
  artan: "Son 7 günün ortalama hacmi son 30 günün {e} katından fazla: ilgi artıyor.",
  kuruma: "Son 7 günün hacmi son 90 günün ortalamasının {e} katından az: ilgi kurumuş.",
};

/** Bir kapsayıcıya tarama ekranını kurar. secenek.istatistik: tarama_istatistik.json içeriği (yoksa null). */
export function ekranKur(kok, secenek = {}) {
  const d = { veri: null, sekme: "dusen", donem: "3a", pazar: "", minHacim: 1e6, varlik: "kripto", sinif: "patlama", siralama: "hacim24",
    istat: secenek.istatistik || null, ...okuAyar() };
  const esik = () => (d.istat && d.istat.esikler) || VARSAYILAN_ESIK;

  const durum = el("p", { class: "soluk" }, "Yükleniyor…");
  const icerik = el("div");
  const sekmeBtn = (ad, metin) => el("button", { "data-s": ad, onclick: () => { d.sekme = ad; kaydetAyar(d); ciz(); } }, metin);
  const sekmeler = el("div", { class: "altsekme tarama-sekme" },
    sekmeBtn("dusen", "En çok düşen"), sekmeBtn("yukselen", "En çok yükselen"), sekmeBtn("hacim", "Hacim"), sekmeBtn("durum", "Hacim durumu"));
  const donemSec = el("div", { class: "dugmeler" }, Object.entries(DONEMLER).map(([k, v]) =>
    el("button", { "data-d": k, onclick: () => { d.donem = k; kaydetAyar(d); ciz(); } }, v.ad)));
  const pazarSec = el("select", { "aria-label": "Piyasa", onchange: (e) => { d.pazar = e.target.value; kaydetAyar(d); ciz(); } },
    el("option", { value: "" }, "Spot + vadeli"), el("option", { value: "vadeli" }, "Vadelide olanlar"),
    el("option", { value: "spot" }, "Yalnız spot"));
  const hacimSec = el("select", { "aria-label": "Minimum 24s hacim", onchange: (e) => { d.minHacim = +e.target.value; kaydetAyar(d); ciz(); } },
    [[0, "Hacim: hepsi"], [1e6, "≥ 1M $"], [1e7, "≥ 10M $"], [5e7, "≥ 50M $"], [2e8, "≥ 200M $"]].map(([v, t]) => el("option", { value: v }, t)));
  const varlikSec = el("select", { "aria-label": "Varlık türü", onchange: (e) => { d.varlik = e.target.value; kaydetAyar(d); ciz(); } },
    el("option", { value: "kripto" }, "Yalnız kripto"), el("option", { value: "hisse" }, "Hisse/ETF tokenleri"),
    el("option", { value: "" }, "Hepsi (altın dahil)"));
  const yenile = el("button", { class: "kucuk ikincil", onclick: () => yukle(true) }, "↻ Yenile");
  kok.replaceChildren(sekmeler, el("div", { class: "filtre" }, donemSec, varlikSec, pazarSec, hacimSec, yenile), durum, icerik);

  function filtreli() {
    return d.veri.satirlar.filter((x) => x.hacim24 >= d.minHacim && (!d.varlik || x.tur === d.varlik)
      && (!d.pazar || (d.pazar === "vadeli" ? x.vadeli : !x.vadeli)));
  }

  function tabloCiz(satirlar, sutunlar) {
    const t = el("table", { class: "tarama-tablo" },
      el("thead", {}, el("tr", {}, el("th", {}, "#"), sutunlar.map((s) => el("th", {}, s[0])))),
      el("tbody", {}, satirlar.map((x, i) => el("tr", {}, el("td", { class: "soluk" }, i + 1),
        sutunlar.map(([, f, sinif]) => el("td", { class: sinif ? sinif(x) : "" }, f(x)))))));
    return el("div", { class: "tablo-kap" }, t);
  }
  const coinHucre = (x) => el("span", { class: "coin" }, x.baz, x.vadeli ? el("i", { class: "rozet-v", title: "Vadelide de işlem görüyor" }, "V") : null);
  const renk = (v) => (x) => (x[v] > 0 ? "pozitif" : x[v] < 0 ? "negatif" : "");
  const hacimEtiket = (x) => hacimSiniflari(x, esik()).map((s) => el("i", { class: "rozet-h " + s, title: SINIF_AD[s] }, SINIF_AD[s])) ;

  function ciz() {
    $$("button", sekmeler).forEach((b) => b.classList.toggle("secili", b.dataset.s === d.sekme));
    $$("button", donemSec).forEach((b) => b.classList.toggle("secili", b.dataset.d === d.donem));
    donemSec.classList.toggle("gizli", d.sekme === "hacim" || d.sekme === "durum");
    pazarSec.value = d.pazar; varlikSec.value = d.varlik; hacimSec.value = String(d.minHacim);
    if (!d.veri) return;
    const g = { "3a": "g90", "6a": "g180", "1y": "g365" }[d.donem];
    let liste = filtreli();
    const yas = new Date(d.veri.zaman);
    durum.textContent = `${d.veri.satirlar.length} coin tarandı · ${yas.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}`
      + (d.veri.vadeli_bilgisi ? "" : " · vadeli listesine ulaşılamadı (V işareti yok)")
      + " · değişimler dünkü günlük kapanışa göre";
    if (d.sekme === "dusen" || d.sekme === "yukselen") {
      const eksik = liste.filter((x) => x[g] == null).length;
      liste = liste.filter((x) => x[g] != null).sort((a, b) => (d.sekme === "dusen" ? a[g] - b[g] : b[g] - a[g])).slice(0, 50);
      icerik.replaceChildren(tabloCiz(liste, [["Coin", coinHucre], [DONEMLER[d.donem].ad, (x) => yuzde(x[g]), renk(g)],
        ["Fiyat", (x) => fiyatMetin(x.fiyat)], ["24s", (x) => yuzde(x.d24), renk("d24")], ["24s hacim $", (x) => usd(x.hacim24)],
        ["Hacim eğilimi", (x) => kat(x.hacim_egilim)], ["Zirveden", (x) => yuzde(x.zirveden, 0)], ["Hacim durumu", hacimEtiket]]),
        el("p", { class: "not" }, `${DONEMLER[d.donem].ad}lık geçmişi olmayan ${eksik} yeni coin bu listeye girmez. Hacim eğilimi: son 7 gün / son 30 gün ortalama hacim.`));
    } else if (d.sekme === "hacim") {
      const sir = { hacim24: (x) => -x.hacim24, egilim: (x) => -(x.hacim_egilim ?? 0), patlama: (x) => -(x.hacim_patlama ?? 0),
        kuruma: (x) => (x.hacim_kuruma ?? 9) }[d.siralama];
      liste = liste.slice().sort((a, b) => sir(a) - sir(b)).slice(0, 50);
      const sirSec = el("select", { "aria-label": "Sıralama", onchange: (e) => { d.siralama = e.target.value; kaydetAyar(d); ciz(); } },
        [["hacim24", "En yüksek 24s hacim"], ["egilim", "Hacmi en çok artan (7g/30g)"], ["patlama", "En büyük hacim patlaması (dün/20g)"],
          ["kuruma", "Hacmi en çok kuruyan (7g/90g)"]].map(([v, t]) => el("option", { value: v }, t)));
      sirSec.value = d.siralama;
      icerik.replaceChildren(el("div", { class: "filtre" }, sirSec), tabloCiz(liste, [["Coin", coinHucre], ["24s hacim $", (x) => usd(x.hacim24)],
        ["30g ort. $", (x) => usd(x.hacim30)], ["7g/30g", (x) => kat(x.hacim_egilim)], ["Dün/20g", (x) => kat(x.hacim_patlama)],
        ["7g/90g", (x) => kat(x.hacim_kuruma)], ["7 gün", (x) => yuzde(x.g7), renk("g7")], ["3 ay", (x) => yuzde(x.g90), renk("g90")]]));
    } else {
      const S = ["patlama", "artan", "kuruma"];
      const secim = el("div", { class: "dugmeler" }, S.map((s) => el("button", { class: s === d.sinif ? "secili" : "",
        onclick: () => { d.sinif = s; kaydetAyar(d); ciz(); } }, SINIF_AD[s])));
      liste = liste.filter((x) => hacimSiniflari(x, esik()).includes(d.sinif));
      const sir = { patlama: (x) => -x.hacim_patlama, artan: (x) => -x.hacim_egilim, kuruma: (x) => x.hacim_kuruma }[d.sinif];
      liste.sort((a, b) => sir(a) - sir(b));
      const ist = d.istat && d.istat.siniflar && d.istat.siniflar[d.sinif];
      icerik.replaceChildren(secim,
        el("p", { class: "aciklama" }, SINIF_ACIKLAMA[d.sinif].replace("{e}", esik()[d.sinif === "patlama" ? "patlama" : d.sinif === "artan" ? "artan" : "kuruma"])),
        istatistikKutusu(ist),
        tabloCiz(liste.slice(0, 50), [["Coin", coinHucre], ["24s hacim $", (x) => usd(x.hacim24)], ["Dün/20g", (x) => kat(x.hacim_patlama)],
          ["7g/30g", (x) => kat(x.hacim_egilim)], ["7g/90g", (x) => kat(x.hacim_kuruma)], ["7 gün", (x) => yuzde(x.g7), renk("g7")],
          ["30 gün", (x) => yuzde(x.g30), renk("g30")], ["3 ay", (x) => yuzde(x.g90), renk("g90")]]),
        el("p", { class: "not" }, `${liste.length} coin bu durumda.`));
    }
  }

  function istatistikKutusu(ist) {
    if (!ist) return el("p", { class: "uyari-kutu" }, "Geçmiş istatistik henüz yok: bu durumdaki coinlerin sonrasında ne yaptığı araştırma tamamlanınca burada gösterilecek.");
    const satir = (u, ad) => u ? el("tr", {}, el("td", {}, ad), el("td", {}, yuzde(u.yukselme_olasiligi - 0, 0).replace("+", "")),
      el("td", { class: u.medyan > 0 ? "pozitif" : "negatif" }, yuzde(u.medyan)), el("td", {}, yuzde(u.piyasa_yukselme_olasiligi, 0).replace("+", ""))) : null;
    return el("div", { class: "kart istat-kutu" },
      el("b", {}, "Geçmişte bu durumdaki coinler sonra ne yaptı?"),
      el("div", { class: "tablo-kap" }, el("table", {}, el("thead", {}, el("tr", {}, ["Süre", "Yükselme olasılığı", "Medyan getiri", "Tüm coinler (karşılaştırma)"].map((x) => el("th", {}, x)))),
        el("tbody", {}, satir(ist.g7, "7 gün sonra"), satir(ist.g30, "30 gün sonra"), satir(ist.g90, "90 gün sonra")))),
      el("p", { class: "not" }, `${ist.olay} olay, ${ist.donem}. Kaynak: Binance arşivi, ${ist.sembol} coin. Geçmiş geleceği garanti etmez.`));
  }

  async function yukle(zorla = false) {
    durum.textContent = "Binance'ten veri alınıyor…";
    try {
      d.veri = await tara({ zorla, ilerleme: (i, n) => { if (i % 20 === 0 || i === n) durum.textContent = `Taranıyor: ${i}/${n} coin…`; } });
      ciz();
    } catch (e) {
      durum.textContent = "Veri alınamadı: " + e.message + ". İnternet bağlantınızı kontrol edin; Binance bölgenizde kısıtlıysa VPN'i kapatın.";
    }
  }
  ciz();
  yukle(false);
  return { yenile: () => yukle(true), istatistik: (x) => { d.istat = x; ciz(); } };
}

const $$ = (s, k = document) => [...k.querySelectorAll(s)];
function okuAyar() { try { return JSON.parse(localStorage.getItem("tarama:ayar") || "{}"); } catch { return {}; } }
function kaydetAyar(d) {
  try { localStorage.setItem("tarama:ayar", JSON.stringify({ sekme: d.sekme, donem: d.donem, pazar: d.pazar, varlik: d.varlik, minHacim: d.minHacim,
    sinif: d.sinif, siralama: d.siralama })); } catch { /* yok */ }
}
