/* Vadeli Tarayıcı — telefon sürümü. Tüm veri textContent ile basılır (HTML kaçışı); kayıtlar yalnızca bu cihazda. */
import * as B from "./binance.js";
import * as S from "./strateji.js";

const $ = (s, k = document) => k.querySelector(s);
const $$ = (s, k = document) => [...k.querySelectorAll(s)];
function el(etiket, oz = {}, ...cocuk) {
  const e = document.createElement(etiket);
  for (const [k, v] of Object.entries(oz || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of cocuk.flat()) if (c !== null && c !== undefined && c !== false) e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
const fmt = {
  f(x) { if (x == null || !isFinite(x)) return "-"; const a = Math.abs(x);
    return a >= 1000 ? x.toLocaleString("tr-TR", { maximumFractionDigits: 2 }) : a >= 1 ? String(+x.toPrecision(6)) : String(+x.toPrecision(5)); },
  d: (x, n = 2) => (x == null || !isFinite(x) ? "-" : Number(x).toFixed(n)),
  y: (x, n = 1) => (x == null || !isFinite(x) ? "-" : (x * 100).toFixed(n) + "%"),
  usd(x) { if (x == null || !isFinite(x)) return "-"; const a = Math.abs(x);
    return a >= 1e9 ? (x / 1e9).toFixed(2) + "B" : a >= 1e6 ? (x / 1e6).toFixed(1) + "M" : a >= 1e3 ? (x / 1e3).toFixed(1) + "K" : x.toFixed(0); },
  zaman: (ms) => new Date(ms).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }),
};
const kv = (k, v, sinif) => el("div", {}, el("span", {}, k), el("b", { class: sinif || "" }, v));
const isaret = (x) => (x > 0 ? "pozitif" : x < 0 ? "negatif" : "");
function toast(m, sure = 4000) { const t = $("#bildirim"); t.textContent = m; t.classList.remove("gizli"); clearTimeout(toast.z); toast.z = setTimeout(() => t.classList.add("gizli"), sure); }

// ------------------------------------------------------------------ yerel kayıt (yalnızca bu cihaz)
const depo = {
  al(k, v) { try { const x = localStorage.getItem("vadeli." + k); return x == null ? v : JSON.parse(x); } catch { return v; } },
  koy(k, v) { try { localStorage.setItem("vadeli." + k, JSON.stringify(v)); } catch { /* özel mod */ } },
};
const ayar = () => ({ hesap: 1000, risk_yuzde: 1, max_kaldirac: 5, sembol_sayisi: 50, ...depo.al("ayar", {}) });
const P = S.VARSAYILAN;
const L = S.TF_MS[P.tf];

// ------------------------------------------------------------------ tarama
const d = { evren: [], satir: new Map(), aktif: [], yaklasan: [], btc: null, sonTarama: 0, sonMum: 0, tarama: false, hata: null };

function durumYaz() {
  const parca = [];
  if (d.tarama) parca.push("taranıyor…");
  else if (d.sonTarama) parca.push(`son tarama ${new Date(d.sonTarama).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}`);
  if (d.sonMum) parca.push(`son 4s mum ${fmt.zaman(d.sonMum)}`);
  if (d.evren.length) parca.push(`${d.satir.size}/${d.evren.length} sembol`);
  if (d.hata) parca.push(d.hata);
  $("#durumMetin").textContent = parca.join(" · ");
  const taze = d.sonMum && Date.now() - (d.sonMum + L) < L + 15 * 60000;
  $("#baglanti").className = "nokta " + (d.hata ? "kirmizi" : taze ? "yesil" : "sari");
}

async function tara() {
  if (d.tarama) return;
  d.tarama = true; d.hata = null; durumYaz();
  const a = ayar();
  try {
    const onbellek = depo.al("evren", null);
    if (onbellek && onbellek.n === a.sembol_sayisi && Date.now() - onbellek.t < 24 * 3600e3) d.evren = onbellek.liste;
    else { d.evren = await B.evren(a.sembol_sayisi); depo.koy("evren", { t: Date.now(), n: a.sembol_sayisi, liste: d.evren }); }
    $("#sembolListe").replaceChildren(...d.evren.map((e) => el("option", { value: e.sembol })));
    const btcM = await B.mumlar("BTCUSDT", P.tf, 1000);
    d.btc = new Map(S.hazirla(btcM, { ...P, btc_filtre: false, oi_teyit: false }).map((x) => [x.t, x.rejim]));
    const pozSembol = depo.al("pozisyonlar", []).filter((p) => p.durum === "acik").map((p) => p.sembol);
    const semboller = [...new Set([...d.evren.map((e) => e.sembol), ...pozSembol])];
    let bitti = 0;
    const sonuc = await B.havuz(semboller, 5, async (s) => {
      const m = s === "BTCUSDT" ? btcM : await B.mumlar(s, P.tf, 1000);
      let satir = S.hazirla(m, { ...P, oi_teyit: false }, d.btc);
      const son = satir[satir.length - 1];
      // Açık pozisyon verisi yalnızca son mumda aday olan sembol için çekilir (aynı sonuç, daha az istek)
      if (son && (son.long_tetik || son.short_tetik || son.long_yakin || son.short_yakin)) {
        let oi = null;
        try { oi = S.oiHizala(m.t, await B.acikPozisyon(s), P.tf); } catch { /* yoksa teyit filtresi sinyali engeller */ }
        satir = S.hazirla(m, P, d.btc, oi);
      } else {
        satir = S.hazirla(m, P, d.btc, null);
      }
      bitti++;
      $("#ilerleme").textContent = `Taranıyor: ${bitti}/${semboller.length}`;
      return [s, satir];
    });
    const hatalar = sonuc.filter((x) => x instanceof Error);
    if (hatalar.length === sonuc.length && hatalar.length) throw hatalar[0];
    d.satir = new Map(sonuc.filter((x) => !(x instanceof Error)));
    const hacim = new Map(d.evren.map((e) => [e.sembol, e.hacim24]));
    const beklenen = Math.floor(Date.now() / L) * L - L;
    const aktif = [], yaklasan = [], yeniler = [];
    for (const [s, satir] of d.satir) {
      if (!hacim.has(s) || !satir.length || satir[satir.length - 1].t < beklenen) continue;
      for (const x of S.sonSinyaller(satir, a, P)) {
        x.sembol = s; x.hacim24 = hacim.get(s);
        (x.tur === "sinyal" ? aktif : yaklasan).push(x);
        const anahtar = `${s}:${x.yon}:${x.zaman}`;
        if (x.tur === "sinyal" && x.yeni && !bildirildi.has(anahtar)) { bildirildi.add(anahtar); yeniler.push(x); }
      }
    }
    depo.koy("bildirildi", [...bildirildi].slice(-300));
    d.aktif = aktif; d.yaklasan = yaklasan;
    d.sonMum = Math.max(0, ...[...d.satir.values()].map((x) => (x.length ? x[x.length - 1].t : 0)));
    d.sonTarama = Date.now();
    $("#ilerleme").textContent = hatalar.length ? `${hatalar.length} sembol alınamadı (tarama devam etti).` : "";
    if (yeniler.length && d.ilkTaramaBitti) haberVer(yeniler);
    d.ilkTaramaBitti = true;
  } catch (e) {
    d.hata = e.message || String(e);
    $("#ilerleme").textContent = d.hata;
  } finally {
    d.tarama = false; durumYaz(); ekranYenile();
  }
}
const bildirildi = new Set(depo.al("bildirildi", []));

async function haberVer(yeniler) {
  const metin = yeniler.map((x) => `${x.yon} ${x.sembol}`).join(", ");
  toast(`Yeni sinyal: ${metin}`, 8000);
  try { navigator.vibrate && navigator.vibrate([200, 100, 200]); } catch { /* yok */ }
  if ("Notification" in window && Notification.permission === "granted") {
    const k = await navigator.serviceWorker?.getRegistration();
    const govde = `${metin}\nKaldıraç zarar riskini büyütür; stop'u borsada gir.`;
    if (k) k.showNotification("Vadeli: yeni sinyal", { body: govde, icon: "ikon-192.png", tag: "sinyal" });
    else new Notification("Vadeli: yeni sinyal", { body: govde });
  }
}

// Her 4 saatlik mum kapanışından ~15 sn sonra otomatik tara; sekmeye dönünce kaçırılanı tara
function zamanla() {
  const sonraki = Math.floor(Date.now() / L) * L + L + 15000;
  setTimeout(async () => { await tara(); zamanla(); }, Math.max(5000, sonraki - Date.now()));
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - d.sonTarama > 5 * 60000
      && Math.floor(Date.now() / L) !== Math.floor(d.sonTarama / L)) tara();
});
$("#yenile").addEventListener("click", () => tara());

// ------------------------------------------------------------------ yönlendirme
function rota() { const h = location.hash.replace(/^#\/?/, "") || "sinyaller"; const [ad, q] = h.split("?"); return { ad, p: new URLSearchParams(q || "") }; }
function rotaYaz(ad, p) { const s = p.toString(); history.replaceState(null, "", "#/" + ad + (s ? "?" + s : "")); }
function ekranYenile() {
  const { ad, p } = rota();
  $$(".ekran").forEach((e) => e.classList.add("gizli"));
  ($("#s-" + ad) || $("#s-sinyaller")).classList.remove("gizli");
  $$("#sekmeler a").forEach((a) => a.classList.toggle("secili", a.dataset.sekme === ad));
  if (ad === "sinyaller") { filtreYukle(p); sinyalCiz(); }
  if (ad === "grafik") grafikAc(p.get("sembol"));
  if (ad === "pozisyonlar") pozCiz(p);
  if (ad === "ayarlar") ayarYukle();
}
window.addEventListener("hashchange", ekranYenile);

// ------------------------------------------------------------------ sinyaller
let alt = "aktif";
function filtreYukle(p) {
  $("#fYon").value = p.get("yon") || ""; $("#fEtiket").value = p.get("etiket") || ""; $("#fSirala").value = p.get("sirala") || "yenilik";
  alt = p.get("alt") === "yaklasan" ? "yaklasan" : "aktif";
  $$(".altsekme button").forEach((b) => b.classList.toggle("secili", b.dataset.alt === alt));
}
function filtreKaydet() {
  const p = new URLSearchParams();
  if ($("#fYon").value) p.set("yon", $("#fYon").value);
  if ($("#fEtiket").value) p.set("etiket", $("#fEtiket").value);
  if ($("#fSirala").value !== "yenilik") p.set("sirala", $("#fSirala").value);
  if (alt !== "aktif") p.set("alt", alt);
  rotaYaz("sinyaller", p); sinyalCiz();
}
["#fYon", "#fEtiket", "#fSirala"].forEach((s) => $(s).addEventListener("change", filtreKaydet));
$$(".altsekme button").forEach((b) => b.addEventListener("click", () => { alt = b.dataset.alt; filtreKaydet();
  $$(".altsekme button").forEach((x) => x.classList.toggle("secili", x === b)); }));

function sinyalCiz() {
  $("#sayAktif").textContent = d.aktif.length; $("#sayYaklasan").textContent = d.yaklasan.length;
  $("#surum").textContent = S.SURUM;
  const yon = $("#fYon").value, et = $("#fEtiket").value, sir = $("#fSirala").value;
  const liste = (alt === "aktif" ? d.aktif : d.yaklasan).filter((x) => (!yon || x.yon === yon) && (!et || (et === "YENI" ? x.yeni : !x.yeni)));
  const anahtar = { yenilik: (x) => [x.yeni ? 0 : 1, -x.hacim24], hacim: (x) => [-x.hacim24], stop: (x) => [x.stop_yuzde] }[sir];
  liste.sort((a, b) => { const A = anahtar(a), C = anahtar(b); for (let i = 0; i < A.length; i++) if (A[i] !== C[i]) return A[i] - C[i]; return 0; });
  const kap = $("#sinyalListe");
  if (!liste.length) {
    kap.replaceChildren(el("p", { class: "soluk" }, d.tarama || !d.sonTarama ? "Taranıyor…"
      : alt === "aktif" ? "Şu an aktif sinyal yok. Sinyaller 4 saatte bir, mum kapanışlarında oluşur." : "Yaklaşan yok."));
    return;
  }
  kap.replaceChildren(...liste.map((x) => {
    const yk = x.tur === "yaklasan";
    return el("div", { class: `kart sinyal ${x.yon}`, onclick: () => { location.hash = `#/grafik?sembol=${encodeURIComponent(x.sembol)}`; } },
      el("div", { class: "ust-satir" }, el("h3", {}, el("span", { class: "yon-" + x.yon }, x.yon), " ", x.sembol),
        yk ? el("span", { class: "etiket" }, "0.5 ATR kala") : el("span", { class: "etiket" + (x.yeni ? " yeni" : "") }, x.yeni ? "YENİ" : "devam")),
      el("div", { class: "izgara" },
        kv(yk ? "Kırılım seviyesi" : "Fiyat", fmt.f(yk ? x.seviye : x.fiyat)), kv("Stop", fmt.f(x.stop)), kv("Stop %", fmt.d(x.stop_yuzde) + "%"),
        kv("Kaldıraç", fmt.d(x.kaldirac, 0) + "x"), kv("Pozisyon", fmt.usd(x.notional) + " $"), kv("Teminat", fmt.usd(x.teminat) + " $"),
        kv("Likidasyon", fmt.f(x.likidasyon)), kv("Risk", fmt.d(x.risk_usdt) + " $"), kv("4s rejim", x.rejim > 0 ? "EMA üstü ▲" : "EMA altı ▼"),
        kv("24s hacim", fmt.usd(x.hacim24) + " $"), kv("Sinyal mumu", fmt.zaman(x.zaman)), kv("Açık poz. değişimi", fmt.y(x.oi_deg), isaret(x.oi_deg))),
      yk ? null : el("button", { class: "kucuk", onclick: (e) => { e.stopPropagation(); pozFormDoldur(x); } }, "Pozisyon aç"));
  }));
}

// ------------------------------------------------------------------ grafik
let grafik = null;
function grafikOlustur() {
  if (grafik) return grafik;
  const koyu = matchMedia("(prefers-color-scheme: dark)").matches;
  const chart = LightweightCharts.createChart($("#grafik"), { autoSize: true,
    layout: { background: { color: "transparent" }, textColor: koyu ? "#c9d1d9" : "#1f2328" },
    grid: { vertLines: { color: koyu ? "#1f2a35" : "#eef1f4" }, horzLines: { color: koyu ? "#1f2a35" : "#eef1f4" } },
    timeScale: { timeVisible: true, secondsVisible: false }, localization: { locale: "tr-TR" } });
  grafik = { chart, cizgi: [],
    mum: chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350" }),
    ema: chart.addLineSeries({ color: "#f0883e", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }),
    ku: chart.addLineSeries({ color: "#4c9aff", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }),
    ka: chart.addLineSeries({ color: "#4c9aff", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }) };
  return grafik;
}
$("#gSembol").addEventListener("change", () => { const s = $("#gSembol").value.trim().toUpperCase(); if (s) location.hash = `#/grafik?sembol=${encodeURIComponent(s)}`; });

async function grafikAc(sembol) {
  sembol = sembol || d.aktif[0]?.sembol || d.evren[0]?.sembol;
  if (!sembol || !/^[A-Z0-9]{2,30}$/.test(sembol)) return;
  $("#gSembol").value = sembol;
  let satir = d.satir.get(sembol);
  if (!satir) {
    try { satir = S.hazirla(await B.mumlar(sembol, P.tf, 1000), { ...P, oi_teyit: false }, d.btc); }
    catch (e) { $("#grafikBilgi").textContent = "Veri alınamadı: " + e.message; return; }
  }
  const g = grafikOlustur();
  const son = satir.slice(-500), sn = (x) => Math.floor(x.t / 1000);
  g.mum.setData(son.map((x) => ({ time: sn(x), open: x.o, high: x.h, low: x.l, close: x.c })));
  const seri = (k) => son.filter((x) => Number.isFinite(x[k])).map((x) => ({ time: sn(x), value: x[k] }));
  g.ema.setData(seri("ema")); g.ku.setData(seri("kanal_ust")); g.ka.setData(seri("kanal_alt"));
  g.mum.setMarkers(son.filter((x) => x.long_yeni || x.short_yeni).map((x) => ({ time: sn(x), position: x.long_yeni ? "belowBar" : "aboveBar",
    color: x.long_yeni ? "#26a69a" : "#ef5350", shape: x.long_yeni ? "arrowUp" : "arrowDown", text: x.long_yeni ? "L" : "S" })));
  g.cizgi.forEach((c) => g.mum.removePriceLine(c)); g.cizgi = [];
  const ekle = (fiyat, renk, baslik) => { if (Number.isFinite(fiyat)) g.cizgi.push(g.mum.createPriceLine({ price: fiyat, color: renk, lineWidth: 1, axisLabelVisible: true, title: baslik })); };
  const a = [...d.aktif, ...d.yaklasan].find((x) => x.sembol === sembol);
  if (a) { ekle(a.tur === "yaklasan" ? a.seviye : a.fiyat, "#8b98a5", a.tur === "yaklasan" ? "kırılım" : "giriş"); ekle(a.stop, "#f0b429", "stop"); ekle(a.likidasyon, "#ef5350", "likidasyon"); }
  for (const p of depo.al("pozisyonlar", []).filter((p) => p.durum === "acik" && p.sembol === sembol)) {
    const e = S.pozisyonDegerlendir(p, satir, P);
    ekle(p.giris, "#c9d1d9", "poz"); ekle(p.stop, "#f0b429", "stop"); ekle(e.onerilen_stop, "#26a69a", "önerilen"); ekle(e.likidasyon, "#ef5350", "likid.");
  }
  const s = satir[satir.length - 1];
  $("#grafikBilgi").textContent = `${sembol} · 4 saat · ATR ${fmt.f(s?.atr)} · rejim ${s?.rejim > 0 ? "EMA üstü" : "EMA altı"}` + (a ? ` · aktif: ${a.yon}` : "");
  g.chart.timeScale().fitContent();
}

// ------------------------------------------------------------------ pozisyonlar (yalnızca bu cihazda)
function pozFormDoldur(x) {
  const f = $("#pozForm");
  f.sembol.value = x.sembol; f.yon.value = x.yon; f.giris.value = x.fiyat; f.notional.value = x.notional.toFixed(2);
  f.kaldirac.value = x.kaldirac; f.stop.value = +x.stop.toPrecision(8);
  f.not.value = `Sinyal ${fmt.zaman(x.zaman)} — giriş fiyatını gerçekleşen fiyatla güncelleyin`;
  location.hash = "#/pozisyonlar?form=1";
}
$("#pozForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, hata = $("#pozHata");
  const sembol = f.sembol.value.trim().toUpperCase().replace("/", "");
  const giris = +f.giris.value, notional = +f.notional.value, k = +f.kaldirac.value, stop = +f.stop.value, yon = f.yon.value;
  if (!/^[A-Z0-9]{2,30}$/.test(sembol)) { hata.textContent = "Geçersiz sembol"; return; }
  if (!(giris > 0 && notional > 0 && stop > 0 && k >= 1 && k <= 125)) { hata.textContent = "Değerleri kontrol edin"; return; }
  if ((giris - stop) * (yon === "LONG" ? 1 : -1) <= 0) { hata.textContent = "Stop, LONG'da girişin altında, SHORT'ta üstünde olmalı"; return; }
  const liste = depo.al("pozisyonlar", []);
  liste.unshift({ id: Date.now(), sembol, yon, giris, adet: notional / giris, kaldirac: k, stop, ilk_stop: stop,
    acilis: Date.now(), durum: "acik", not: f.not.value.slice(0, 500) });
  depo.koy("pozisyonlar", liste);
  f.reset(); hata.textContent = ""; $("#pozFormKutu").open = false; toast("Pozisyon kaydedildi");
  if (!d.satir.has(sembol)) tara(); else pozCiz();
});
function pozGuncelle(id, fn) { const l = depo.al("pozisyonlar", []); const p = l.find((x) => x.id === id); if (p) { fn(p); depo.koy("pozisyonlar", l); } pozCiz(); }

function pozCiz(p) {
  if (p && p.get("form")) $("#pozFormKutu").open = true;
  const liste = depo.al("pozisyonlar", []);
  const kap = $("#pozListe");
  if (!liste.length) { kap.replaceChildren(el("p", { class: "soluk" }, "Kayıtlı pozisyon yok.")); return; }
  kap.replaceChildren(...liste.map((x) => {
    const acik = x.durum === "acik";
    const e = acik ? S.pozisyonDegerlendir(x, d.satir.get(x.sembol), P) : { pnl: x.pnl, r: x.r, likidasyon: S.likidasyon(x.giris, x.yon === "LONG" ? 1 : -1, x.kaldirac, P.mmr), notlar: [] };
    return el("div", { class: `kart sinyal ${x.yon}` },
      el("div", { class: "ust-satir" }, el("h3", {}, el("span", { class: "yon-" + x.yon }, x.yon), " ", x.sembol),
        el("span", { class: "etiket" + (acik ? " yeni" : "") }, acik ? "açık" : "kapalı")),
      el("div", { class: "izgara" },
        kv("Giriş", fmt.f(x.giris)), kv("Kaldıraç", fmt.d(x.kaldirac, 0) + "x"), kv(acik ? "Son fiyat" : "Kapanış", fmt.f(acik ? e.son_fiyat : x.kapanis_fiyat)),
        kv("K/Z", fmt.d(e.pnl) + " $", isaret(e.pnl)), kv("R katı", e.r == null ? "-" : fmt.d(e.r) + "R", isaret(e.r)),
        kv("Borsadaki stop", fmt.f(x.stop)), kv("Önerilen stop", fmt.f(e.onerilen_stop)), kv("Likidasyon", fmt.f(e.likidasyon))),
      acik ? e.notlar.map((n) => el("div", { class: "poz-uyari" + (/LİKİDASYON|ÇIKIŞ|geçti/.test(n) ? " ciddi" : "") }, n)) : null,
      x.not ? el("p", { class: "soluk" }, "Not: " + x.not) : null,
      el("div", { class: "filtre" },
        acik && e.stop_degisti ? el("button", { class: "kucuk", onclick: () => pozGuncelle(x.id, (p) => { p.stop = e.onerilen_stop; }) }, "Stopu önerilene çektim") : null,
        acik ? el("button", { class: "kucuk ikincil", onclick: () => { const v = +prompt("Borsada girdiğiniz yeni stop:", x.stop); if (v > 0) pozGuncelle(x.id, (p) => { p.stop = v; }); } }, "Stop gir") : null,
        acik ? el("button", { class: "kucuk ikincil", onclick: () => { const v = +prompt("Kapanış fiyatı:", e.son_fiyat ?? x.giris); if (!(v > 0)) return;
          pozGuncelle(x.id, (p) => { const y = p.yon === "LONG" ? 1 : -1; p.durum = "kapali"; p.kapanis_fiyat = v; p.pnl = y * p.adet * (v - p.giris);
            const risk = Math.abs(p.giris - p.ilk_stop) * p.adet; p.r = risk ? p.pnl / risk : null; }); } }, "Kapat") : null,
        el("button", { class: "kucuk tehlike", onclick: () => { if (confirm(`${x.sembol} kaydı silinsin mi?`)) { depo.koy("pozisyonlar", depo.al("pozisyonlar", []).filter((p) => p.id !== x.id)); pozCiz(); } } }, "Sil"),
        el("button", { class: "kucuk ikincil", onclick: () => { location.hash = `#/grafik?sembol=${x.sembol}`; } }, "Grafik")));
  }));
}

// ------------------------------------------------------------------ ayarlar ve kurulum
function ayarYukle() { const a = ayar(), f = $("#ayarForm"); for (const k of ["hesap", "risk_yuzde", "max_kaldirac", "sembol_sayisi"]) f[k].value = a[k]; }
$("#ayarForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, a = { hesap: +f.hesap.value, risk_yuzde: +f.risk_yuzde.value, max_kaldirac: +f.max_kaldirac.value, sembol_sayisi: Math.round(+f.sembol_sayisi.value) };
  if (!(a.hesap >= 10 && a.risk_yuzde >= 0.05 && a.risk_yuzde <= 5 && a.max_kaldirac >= 1 && a.max_kaldirac <= 50 && a.sembol_sayisi >= 5 && a.sembol_sayisi <= 100)) {
    $("#ayarMesaj").textContent = "Değerleri kontrol edin."; return;
  }
  depo.koy("ayar", a); $("#ayarMesaj").textContent = "Kaydedildi; yeniden taranıyor."; tara();
});
$("#bildirimIzni").addEventListener("click", async () => {
  if (!("Notification" in window)) { toast("Bu tarayıcı bildirimi desteklemiyor (iPhone'da önce Ana Ekrana Ekle)."); return; }
  toast((await Notification.requestPermission()) === "granted" ? "Bildirim izni verildi" : "İzin verilmedi");
});

const kurulu = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const ios = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
let kurIstegi = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); kurIstegi = e; $("#yukleDugme").classList.remove("gizli"); $("#kurBandiDugme").classList.remove("gizli"); bantGoster(); });
async function yukle() { if (!kurIstegi) return; kurIstegi.prompt(); await kurIstegi.userChoice; kurIstegi = null; $("#kurBandi").classList.add("gizli"); $("#yukleDugme").classList.add("gizli"); }
$("#yukleDugme").addEventListener("click", yukle); $("#kurBandiDugme").addEventListener("click", yukle);
$("#kurBandiKapat").addEventListener("click", () => { $("#kurBandi").classList.add("gizli"); depo.koy("bantKapali", true); });
function bantGoster() {
  if (kurulu() || depo.al("bantKapali", false)) return;
  $("#kurBandiMetin").textContent = ios() ? "Uygulama gibi açmak için: Paylaş ⬆︎ → Ana Ekrana Ekle" : kurIstegi ? "Telefona uygulama olarak yükleyin." : "Tarayıcı menüsünden: Ana ekrana ekle";
  $("#kurBandi").classList.remove("gizli");
}

// ------------------------------------------------------------------ başlat
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
bantGoster();
ekranYenile();
tara().then(zamanla);
