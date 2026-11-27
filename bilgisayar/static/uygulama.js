/* Vadeli Tarayıcı arayüzü — derleme gerektirmez. Tüm veriler textContent ile basılır (HTML kaçışı). */
"use strict";

const $ = (s, k = document) => k.querySelector(s);
const $$ = (s, k = document) => [...k.querySelectorAll(s)];

function el(etiket, ozellik = {}, ...cocuklar) {
  const e = document.createElement(etiket);
  for (const [k, v] of Object.entries(ozellik || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of cocuklar.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

const fmt = {
  f(x) { if (x == null || !isFinite(x)) return "-"; const a = Math.abs(x);
    return a >= 1000 ? x.toLocaleString("tr-TR", { maximumFractionDigits: 2 }) : a >= 1 ? x.toPrecision(6).replace(/\.?0+$/, "") : x.toPrecision(5); },
  d(x, n = 2) { return x == null || !isFinite(x) ? "-" : Number(x).toFixed(n); },
  y(x, n = 1) { return x == null || !isFinite(x) ? "-" : (x * 100).toFixed(n) + "%"; },
  usd(x) { if (x == null || !isFinite(x)) return "-"; const a = Math.abs(x);
    return a >= 1e9 ? (x / 1e9).toFixed(2) + "B" : a >= 1e6 ? (x / 1e6).toFixed(1) + "M" : a >= 1e3 ? (x / 1e3).toFixed(1) + "K" : x.toFixed(0); },
  zaman(iso) { if (!iso) return "-"; const d = new Date(iso);
    return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); },
};
const isaretSinif = (x) => (x > 0 ? "pozitif" : x < 0 ? "negatif" : "");

function toast(metin, sure = 4000) {
  const t = $("#bildirim");
  t.textContent = metin;
  t.classList.remove("gizli");
  clearTimeout(toast._z);
  toast._z = setTimeout(() => t.classList.add("gizli"), sure);
}

async function api(yol, secenek = {}) {
  const o = { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...secenek };
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  const r = await fetch(yol, o);
  if (r.status === 401 && !yol.startsWith("/api/giris")) { girisGoster(); throw new Error("giriş gerekli"); }
  let veri = null;
  try { veri = await r.json(); } catch { /* boş */ }
  if (!r.ok) throw new Error((veri && (veri.detail?.[0]?.msg || veri.detail || veri.hata)) || r.statusText);
  return veri;
}

// ------------------------------------------------------------------ yönlendirme (filtreler URL'de)
const durum = { sinyaller: { aktif: [], yaklasan: [], evren: [] }, alt: "aktif", grafik: null, grafikSembol: null,
  aralik: "1h", bt: null, sse: null };

function rota() {
  const h = location.hash.replace(/^#\/?/, "") || "analiz";
  const [ad, sorgu] = h.split("?");
  return { ad, p: new URLSearchParams(sorgu || "") };
}
function rotaYaz(ad, p) {
  const s = p.toString();
  history.replaceState(null, "", "#/" + ad + (s ? "?" + s : ""));
}

function ekranGoster() {
  const { ad, p } = rota();
  $$(".ekran").forEach((e) => e.classList.add("gizli"));
  const ekran = $("#s-" + ad) || $("#s-sinyaller");
  ekran.classList.remove("gizli");
  $$("#sekmeler a").forEach((a) => a.classList.toggle("secili", a.dataset.sekme === ad));
  if (ad === "sinyaller") { filtreleriYukle(p); sinyalleriCiz(); }
  if (ad === "grafik") { const s = p.get("sembol"); durum.aralik = p.get("aralik") === "4h" ? "4h" : "1h"; grafikAc(s); }
  if (ad === "pozisyonlar") pozisyonlariYukle(p);
  if (ad === "piyasa") { durum.haritaD = p.get("d") || "d24s"; $("#haritaVadeli").checked = p.get("vadeli") === "1"; piyasaYukle(); }
  if (ad === "gecmis") gecmisYukle();
  if (ad === "backtest") backtestYukle(p.get("varyant"));
  if (ad === "ayarlar") { ayarlariYukle(); telefonKartiYukle(); }
}
window.addEventListener("hashchange", ekranGoster);

// ------------------------------------------------------------------ giriş
function girisGoster() {
  $$(".ekran").forEach((e) => e.classList.add("gizli"));
  $("#s-giris").classList.remove("gizli");
  $("#sekmeler").classList.add("gizli");
}
$("#girisForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#girisHata").textContent = "";
  try {
    await api("/api/giris", { method: "POST", body: { parola: $("#girisParola").value } });
    $("#girisParola").value = "";
    $("#sekmeler").classList.remove("gizli");
    baslat();
  } catch (err) { $("#girisHata").textContent = err.message; }
});

// ------------------------------------------------------------------ durum çubuğu ve canlı akış (SSE)
function durumYaz(d) {
  if (!d) return;
  const son = d.son_tarama ? new Date(d.son_tarama * 1000) : null;
  const gec = d.gecikme_sn;
  const saglik = d.sembol ? `${d.saglikli_sembol}/${d.sembol}` : "-";
  let metin = son ? `son tarama ${son.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}` : "ilk tarama bekleniyor";
  if (d.sanal_saat) metin += ` · DEMO saat ${fmt.zaman(d.sanal_saat)}`;
  metin += ` · veri ${saglik}`;
  if (gec != null) metin += ` · mum gecikmesi ${Math.round(gec)} sn`;
  if (d.hatali_sayi) metin += ` · ${d.hatali_sayi} hata`;
  $("#durumMetin").textContent = metin;
  const veriTaze = d.kaynak === "demo" || (gec != null && gec < 3700 + 120);
  $("#baglanti").className = "nokta " + (!durum.sseBagli ? "kirmizi" : veriTaze && d.saglikli_sembol >= d.sembol * 0.9 ? "yesil" : "sari");
  $("#baglanti").title = durum.sseBagli ? (veriTaze ? "Canlı, veri taze" : "Canlı, veri gecikmeli") : "Bağlantı koptu — yeniden deneniyor";
}

function sseBaslat() {
  if (durum.sse) durum.sse.close();
  const es = new EventSource("/api/olaylar");
  durum.sse = es;
  es.addEventListener("merhaba", (e) => { durum.sseBagli = true; durumYaz(JSON.parse(e.data)); });
  es.addEventListener("nabiz", () => { durum.sseBagli = true; });
  es.addEventListener("tarama", async (e) => {
    const v = JSON.parse(e.data);
    durumYaz(v.durum);
    await sinyalleriYukle();
    const { ad } = rota();
    if (ad === "pozisyonlar") pozisyonlariYukle();
    if (ad === "grafik" && durum.grafikSembol) grafikAc(durum.grafikSembol, true);
    if (ad === "gecmis") gecmisYukle();
    if (v.yeni) toast(`${v.yeni} yeni sinyal`);
  });
  es.addEventListener("pozisyon", (e) => {
    const u = JSON.parse(e.data);
    u.forEach((x) => toast(`${x.sembol} #${x.id}: ${x.degerlendirme}`, 8000));
    if (rota().ad === "pozisyonlar") pozisyonlariYukle();
  });
  es.addEventListener("backtest", () => { if (rota().ad === "backtest") backtestYukle(); });
  es.addEventListener("ileri_test", () => { ileriTestYukle(); toast("İleri test güncellendi"); });
  es.onerror = () => { durum.sseBagli = false; $("#baglanti").className = "nokta kirmizi";
    $("#baglanti").title = "Bağlantı koptu — yeniden deneniyor"; };
}

// ------------------------------------------------------------------ sinyaller
function filtreleriYukle(p) {
  $("#fYon").value = p.get("yon") || "";
  $("#fEtiket").value = p.get("etiket") || "";
  $("#fSet").value = p.get("set") || "";
  $("#fHacim").value = p.get("hacim") || "0";
  $("#fAra").value = p.get("ara") || "";
  $("#fSirala").value = p.get("sirala") || "yenilik";
  durum.alt = p.get("alt") === "yaklasan" ? "yaklasan" : "aktif";
  $$(".altsekme button").forEach((b) => b.classList.toggle("secili", b.dataset.alt === durum.alt));
}
function filtreleriKaydet() {
  const p = new URLSearchParams();
  if ($("#fYon").value) p.set("yon", $("#fYon").value);
  if ($("#fEtiket").value) p.set("etiket", $("#fEtiket").value);
  if ($("#fSet").value) p.set("set", $("#fSet").value);
  if ($("#fHacim").value !== "0") p.set("hacim", $("#fHacim").value);
  if ($("#fAra").value.trim()) p.set("ara", $("#fAra").value.trim());
  if ($("#fSirala").value !== "yenilik") p.set("sirala", $("#fSirala").value);
  if (durum.alt !== "aktif") p.set("alt", durum.alt);
  rotaYaz("sinyaller", p);
  sinyalleriCiz();
}
["#fYon", "#fSet", "#fEtiket", "#fHacim", "#fSirala"].forEach((s) => $(s).addEventListener("change", filtreleriKaydet));
$("#fAra").addEventListener("input", filtreleriKaydet);
$$(".altsekme button").forEach((b) => b.addEventListener("click", () => { durum.alt = b.dataset.alt; filtreleriKaydet();
  $$(".altsekme button").forEach((x) => x.classList.toggle("secili", x === b)); }));

async function sinyalleriYukle() {
  try {
    durum.sinyaller = await api("/api/sinyaller");
    try { durum.acikPoz = (await api("/api/pozisyonlar")).pozisyonlar.filter((x) => x.durum === "acik").length; } catch { /* yok */ }
    durumYaz(durum.sinyaller.durum);
    $("#tetikTf").textContent = durum.sinyaller.tetik_tf === "4h" ? "4s" : "1s";
    $("#paramMetin").textContent = "Strateji: " + (durum.sinyaller.param || "");
    const dl = $("#sembolListe");
    dl.replaceChildren(...durum.sinyaller.evren.map((e) => el("option", { value: e.sembol })));
    if (rota().ad === "sinyaller") { sinyalleriCiz(); ozetSeritCiz(); }
  } catch (e) { console.warn(e); }
}

function sinyalleriCiz() {
  const { aktif, yaklasan } = durum.sinyaller;
  $("#sayAktif").textContent = aktif.length;
  $("#sayYaklasan").textContent = yaklasan.length;
  let liste = (durum.alt === "aktif" ? aktif : yaklasan).slice();
  const yon = $("#fYon").value, et = $("#fEtiket").value, hac = Number($("#fHacim").value), ara = $("#fAra").value.trim().toUpperCase();
  const set = $("#fSet").value;
  liste = liste.filter((x) => (!set || x.ana_set !== false) && (!yon || x.yon === yon) && (!et || (et === "YENI" ? x.yeni : !x.yeni))
    && (x.hacim24 || 0) >= hac && (!ara || x.sembol.includes(ara)));
  const sir = $("#fSirala").value;
  const anahtar = { yenilik: (x) => [x.yeni ? 0 : 1, -(x.hacim24 || 0)], hacim: (x) => [-(x.hacim24 || 0)],
    stop: (x) => [x.stop_yuzde], risk: (x) => [-x.risk_usdt] }[sir];
  liste.sort((a, b) => { const A = anahtar(a), B = anahtar(b); for (let i = 0; i < A.length; i++) if (A[i] !== B[i]) return A[i] - B[i]; return 0; });
  const kap = $("#sinyalListe");
  if (!liste.length) { kap.replaceChildren(el("p", { class: "soluk" }, durum.alt === "aktif" ? "Filtreye uyan aktif sinyal yok." : "Yaklaşan yok.")); return; }
  kap.replaceChildren(...liste.map(sinyalKarti));
}

function sinyalKarti(x) {
  const yaklasan = x.tur === "yaklasan";
  const kart = el("div", { class: `kart sinyal ${x.yon}`, tabindex: 0, onclick: () => { location.hash = `#/grafik?sembol=${encodeURIComponent(x.sembol)}`; } },
    el("div", { class: "ust-satir" },
      el("h3", {}, el("span", { class: "yon-" + x.yon }, x.yon), " ", x.sembol),
      el("span", { class: "etiketler" },
        x.ana_set === false ? el("span", { class: "etiket dis", title: "Bu coin doğrulanan 22'lik ana sette değil. Ana set dışındaki coinlerde backtest kenarı çok zayıf (+0.025 R/işlem)." }, "ana set dışı") : null,
        yaklasan ? el("span", { class: "etiket" }, "0.5 ATR kala") : el("span", { class: "etiket" + (x.yeni ? " yeni" : "") }, x.yeni ? "YENİ" : "devam"))),
    el("div", { class: "izgara" },
      kv(yaklasan ? "Kırılım seviyesi" : "Fiyat", fmt.f(yaklasan ? x.seviye : x.fiyat)),
      kv("Stop", fmt.f(x.stop)), kv("Stop %", fmt.d(x.stop_yuzde) + "%"),
      kv("Kaldıraç", fmt.d(x.kaldirac, 0) + "x"), kv("Pozisyon", fmt.usd(x.notional) + " $"), kv("Teminat", fmt.usd(x.teminat) + " $"),
      kv("Likidasyon", fmt.f(x.likidasyon)), kv("Risk", fmt.d(x.risk_usdt) + " $"), kv("4s rejim", x.rejim > 0 ? "EMA üstü ▲" : "EMA altı ▼"),
      kv("24s hacim", fmt.usd(x.hacim24) + " $"), kv("Sinyal mumu", fmt.zaman(x.zaman) + (x.tetik_tf === "4h" ? " (4s)" : "")),
      kv("Kapanıştan beri", x.yas_saat == null ? "-" : fmt.d(x.yas_saat, 1) + " sa"),
      x.oi_deg !== undefined ? kv("Açık poz. değişimi", fmt.y(x.oi_deg)) : null),
    yaklasan ? null : borsaKutusu(x),
    yaklasan ? null : el("button", { class: "kucuk", onclick: (e) => { e.stopPropagation(); pozisyonFormuDoldur(x); } }, "Girdim, kaydet"));
  kart.addEventListener("keydown", (e) => { if (e.key === "Enter") kart.click(); });
  return kart;
}
const kv = (k, v) => el("div", {}, el("span", {}, k), el("b", {}, v));

// Borsaya elle girilecek değerler: kopyala düğmeli. Miktar adet cinsinden (Binance "Boyut" alanı, coin birimi).
function kopyalanir(etiket, deger, aciklama) {
  const d = el("button", { class: "kopya", type: "button", title: "Kopyala", onclick: async (e) => {
    e.stopPropagation();
    try { await navigator.clipboard.writeText(deger); toast(`${etiket} kopyalandı: ${deger}`, 2500); }
    catch { toast(`${etiket}: ${deger}`, 6000); }
  } }, "⧉");
  return el("div", { class: "borsa-satir" }, el("span", {}, etiket), el("b", {}, deger), d, aciklama ? el("i", {}, aciklama) : null);
}
const sayiMetin = (x, basamak) => { if (x == null || !isFinite(x)) return "-";
  const n = basamak ?? (Math.abs(x) >= 100 ? 2 : Math.abs(x) >= 1 ? 4 : 6); return Number(x).toFixed(n).replace(/\.?0+$/, ""); };
function borsaKutusu(x) {
  const yon = x.yon === "LONG" ? "Al / Long" : "Sat / Short";
  return el("div", { class: "borsa-kutu", onclick: (e) => e.stopPropagation() },
    el("div", { class: "borsa-baslik" }, "Binance'e girilecekler"),
    el("ol", { class: "borsa-adim" },
      el("li", {}, `Marjin: İzole · Kaldıraç ${fmt.d(x.kaldirac, 0)}x`),
      el("li", {}, `Piyasa emri (Market) · ${yon}`),
      el("li", {}, "Hemen ardından Stop-Market emri (Reduce-only / Pozisyonu kapat)")),
    kopyalanir("Miktar", sayiMetin(x.adet), `≈ ${fmt.usd(x.notional)} $`),
    kopyalanir("Stop", sayiMetin(x.stop), `${fmt.d(x.stop_yuzde)}% uzakta`),
    el("p", { class: "not" }, `Risk ≈ ${fmt.d(x.risk_usdt)} $ (stop + komisyon). Backtest girişi sinyalden sonraki mumun açılışında varsayar; çok geç girerseniz sonuç farklı olabilir.`));
}

// Tek hesapta toplam açık risk tavanı (RAPOR.md §1c: işlemlerin çoğu aynı anda, aynı yönde açılıyor)
const ACIK_TAVAN = 5;
// Sinyaller ekranı üst şeridi: sonraki mum kapanışı + ileri test durumu
function ozetSeritCiz() {
  const kap = $("#ozetSerit"); if (!kap) return;
  const tf = durum.sinyaller.tetik_tf === "4h" ? 4 : 1;
  const sanal = durum.sinyaller.durum?.sanal_saat;
  const simdi = sanal ? new Date(sanal).getTime() : Date.now();
  const adim = tf * 3600e3, sonraki = Math.floor(simdi / adim) * adim + adim, kalan = Math.max(0, sonraki - simdi);
  const sa = Math.floor(kalan / 3600e3), dk = Math.floor((kalan % 3600e3) / 60e3);
  const it = durum.ileriTest;
  const itMetin = it ? `${it.karar.durum === "dur" ? "DUR" : it.karar.durum === "uygun" ? "uygun" : it.karar.durum === "erken" ? "erken" : "izle"} · ${it.ozet.islem} işlem · ort. R ${fmt.d(it.ozet.ort_r, 3)}` : "henüz hesaplanmadı";
  kap.replaceChildren(
    el("div", {}, el("span", {}, "Sonraki sinyal kontrolü"), el("b", {}, `${sa} sa ${dk} dk`),
      el("i", {}, `${tf === 4 ? "4s" : "1s"} mum kapanışı ${new Date(sonraki).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}`)),
    el("div", {}, el("span", {}, "Aktif sinyal"), el("b", {}, String(durum.sinyaller.aktif.length)),
      el("i", {}, `${durum.sinyaller.yaklasan.length} yaklaşan`)),
    el("a", { href: "#/pozisyonlar", class: "acik-risk" + ((durum.acikPoz ?? 0) >= ACIK_TAVAN ? " dolu" : "") },
      el("span", {}, "Açık pozisyon / tavan"), el("b", {}, `${durum.acikPoz ?? 0} / ${ACIK_TAVAN}`),
      el("i", {}, (durum.acikPoz ?? 0) >= ACIK_TAVAN ? "Tavan dolu: yeni sinyale girme" : "Tek hesapta en fazla 5 açık pozisyon")),
    el("a", { href: "#/gecmis", class: "ileri-link " + (it ? "d-" + it.karar.durum : "") }, el("span", {}, "İleri test"), el("b", {}, itMetin),
      el("i", {}, it ? `${it.baslangic.slice(0, 10)}'den beri · ayrıntı →` : "Geçmiş → İleri test")));
}
setInterval(() => { if (rota().ad === "sinyaller") ozetSeritCiz(); }, 30e3);

// ------------------------------------------------------------------ ileri test
function svg(etiket, oz = {}) { const e = document.createElementNS("http://www.w3.org/2000/svg", etiket);
  for (const [k, v] of Object.entries(oz)) e.setAttribute(k, v); return e; }

function ileriGrafik(egri) {
  const G = 640, Y = 220, sol = 40, sag = 10, ust = 10, alt = 24;
  const s = svg("svg", { viewBox: `0 0 ${G} ${Y}`, class: "ileri-grafik", role: "img",
    "aria-label": "Kümülatif R ve beklenti bandı" });
  if (!egri.length) return s;
  const n = egri.length, xs = (i) => sol + (G - sol - sag) * (n === 1 ? 0.5 : (i - 1) / (n - 1));
  const tum = egri.flatMap((e) => [e.kum_r, e.alt ?? e.kum_r, e.ust ?? e.kum_r, 0]);
  const mn = Math.min(...tum), mx = Math.max(...tum), aralik = mx - mn || 1;
  const ys = (v) => ust + (Y - ust - alt) * (1 - (v - mn) / aralik);
  const yol = (f) => egri.map((e, k) => `${k ? "L" : "M"}${xs(e.n).toFixed(1)},${ys(f(e)).toFixed(1)}`).join("");
  if (egri[0].alt != null) {
    const bant = yol((e) => e.ust) + egri.slice().reverse().map((e) => `L${xs(e.n).toFixed(1)},${ys(e.alt).toFixed(1)}`).join("") + "Z";
    s.appendChild(svg("path", { d: bant, class: "bant" }));
    s.appendChild(svg("path", { d: yol((e) => e.beklenen), class: "beklenen" }));
  }
  s.appendChild(svg("line", { x1: sol, x2: G - sag, y1: ys(0), y2: ys(0), class: "sifir" }));
  s.appendChild(svg("path", { d: yol((e) => e.kum_r), class: "gercek" }));
  for (const v of [mn, 0, mx]) { const t = svg("text", { x: sol - 4, y: ys(v) + 4, class: "eksen", "text-anchor": "end" });
    t.textContent = (v > 0 ? "+" : "") + v.toFixed(1); s.appendChild(t); }
  const t = svg("text", { x: G - sag, y: Y - 6, class: "eksen", "text-anchor": "end" }); t.textContent = `${n} işlem`; s.appendChild(t);
  return s;
}

async function ileriTestYukle() {
  let v; try { v = await api("/api/ileri-test"); } catch { return; }
  const kap = $("#ileriTest"), rp = v.rapor, c = v.calisma || {};
  durum.ileriTest = rp;
  const dugme = el("button", { class: "kucuk ikincil", disabled: c.calisiyor || null, onclick: async () => {
    try { await api("/api/ileri-test/calistir", { method: "POST" }); toast("İleri test güncelleniyor (1-3 dk)…"); ileriTestYukle(); }
    catch (e) { toast(e.message); } } }, c.calisiyor ? "Güncelleniyor…" : "Şimdi güncelle");
  if (!rp) {
    kap.replaceChildren(el("h3", {}, "İleri test"), el("p", { class: "soluk" },
      "Henüz hesaplanmadı. Dondurulmuş strateji 2026-11-01'den beri hiçbir analizde kullanılmamış veride Binance arşivinden hesaplanır."), dugme);
    return;
  }
  const o = rp.ozet, b = rp.beklenti, k = rp.karar;
  const ilerleme = Math.min(1, o.islem / 200);
  kap.replaceChildren(
    el("div", { class: "ileri-ust" }, el("h3", {}, "İleri test"), el("span", { class: "karar d-" + k.durum },
      { erken: "ERKEN", izle: "İZLE", dur: "DUR", uygun: "UYGUN" }[k.durum] || k.durum), dugme),
    el("p", { class: "karar-metin" }, k.metin),
    el("div", { class: "ilerleme", title: `${o.islem}/200 işlem` }, el("div", { style: `width:${(ilerleme * 100).toFixed(1)}%` }),
      el("i", { style: "left:25%" }), el("i", { style: "left:50%" })),
    el("div", { class: "ilerleme-etiket soluk" }, el("span", {}, "0"), el("span", {}, "50"), el("span", {}, "100: ilk karar"), el("span", {}, "200: son karar")),
    el("div", { class: "istat" },
      el("div", { class: "kart" }, el("span", {}, "Kapanan işlem"), el("b", {}, String(o.islem)),
        rp.beklenen_islem ? el("span", {}, `beklenen ~${Math.round(rp.beklenen_islem)}`) : null),
      el("div", { class: "kart" }, el("span", {}, "Ort. R"), el("b", { class: isaretSinif(o.ort_r) }, fmt.d(o.ort_r, 3)),
        b ? el("span", {}, `backtest ${fmt.d(b.ort_r, 3)}`) : null),
      el("div", { class: "kart" }, el("span", {}, "Toplam R"), el("b", { class: isaretSinif(o.toplam_r) }, fmt.d(o.toplam_r, 1)),
        el("span", {}, `%1 riskle ≈ ${fmt.d(o.toplam_r, 1)}%`)),
      el("div", { class: "kart" }, el("span", {}, "Kazanma"), el("b", {}, fmt.y(o.kazanma)), el("span", {}, `açık: ${rp.acik.length}`))),
    ileriGrafik(rp.egri),
    el("p", { class: "not" }, "Mavi: gerçekleşen kümülatif R · kesikli: backtest beklentisi · gri bant: beklenti ± 2σ√n. "
      + `Strateji ${rp.strateji} (${rp.surum}), ${rp.evren.length} sembol, veri ${fmt.zaman(rp.son_veri)} UTC'ye kadar `
      + `(Binance arşivi bir gün gecikmeli). Güncelleme: ${rp.olusturma}.`),
    el("details", {}, el("summary", {}, "Kurallar (önceden yazıldı) ve işlemler"),
      el("ul", {}, rp.kurallar.map((x) => el("li", {}, x))),
      el("div", { class: "tablo-kap" }, (() => { const t = el("table", { id: "ileriTablo" }); return t; })())));
  tablo("#ileriTablo", [["Sembol", (r) => r.sembol], ["Yön", (r) => r.yon, (r) => "yon-" + r.yon],
    ["Giriş", (r) => fmt.zaman(r.giris_zaman)], ["Çıkış", (r) => (r.neden === "donem_sonu" ? "açık" : fmt.zaman(r.cikis_zaman))],
    ["Neden", (r) => (r.neden === "donem_sonu" ? "-" : r.neden)], ["R", (r) => fmt.d(r.r), (r) => isaretSinif(r.r)]],
    [...rp.acik, ...rp.islemler]);
  if (rota().ad === "sinyaller") ozetSeritCiz();
}

// ------------------------------------------------------------------ grafik
function grafikOlustur() {
  if (durum.grafik) return durum.grafik;
  const kap = $("#grafik");
  const koyu = matchMedia("(prefers-color-scheme: dark)").matches;
  const chart = LightweightCharts.createChart(kap, {
    autoSize: true, layout: { background: { color: "transparent" }, textColor: koyu ? "#c9d1d9" : "#1f2328" },
    grid: { vertLines: { color: koyu ? "#1f2a35" : "#eef1f4" }, horzLines: { color: koyu ? "#1f2a35" : "#eef1f4" } },
    timeScale: { timeVisible: true, secondsVisible: false }, rightPriceScale: { borderVisible: false },
    localization: { locale: "tr-TR" },
  });
  const mum = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350" });
  const ema = chart.addLineSeries({ color: "#f0883e", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  const ku = chart.addLineSeries({ color: "#4c9aff", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
  const ka = chart.addLineSeries({ color: "#4c9aff", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
  durum.grafik = { chart, mum, ema, ku, ka, cizgiler: [] };
  return durum.grafik;
}

$$("#s-grafik .dugmeler button").forEach((b) => b.addEventListener("click", () => {
  durum.aralik = b.dataset.aralik;
  const p = new URLSearchParams(); if (durum.grafikSembol) p.set("sembol", durum.grafikSembol); p.set("aralik", durum.aralik);
  rotaYaz("grafik", p); grafikAc(durum.grafikSembol);
}));
$("#gSembol").addEventListener("change", () => {
  const s = $("#gSembol").value.trim().toUpperCase(); if (!s) return;
  const p = new URLSearchParams({ sembol: s, aralik: durum.aralik }); rotaYaz("grafik", p); grafikAc(s);
});

async function grafikAc(sembol, sessiz = false) {
  $$("#s-grafik .dugmeler button").forEach((b) => b.classList.toggle("secili", b.dataset.aralik === durum.aralik));
  if (!sembol) { sembol = durum.sinyaller.aktif[0]?.sembol || durum.sinyaller.evren[0]?.sembol; if (!sembol) return; }
  durum.grafikSembol = sembol;
  $("#gSembol").value = sembol;
  let v;
  try { v = await api(`/api/mumlar?sembol=${encodeURIComponent(sembol)}&aralik=${durum.aralik}&limit=500`); }
  catch (e) { if (!sessiz) $("#grafikBilgi").textContent = "Grafik verisi alınamadı: " + e.message; return; }
  const g = grafikOlustur();
  g.mum.setData(v.mumlar.map(([t, o, h, l, c]) => ({ time: t, open: o, high: h, low: l, close: c })));
  const cizgi = (arr) => arr.map(([t, x]) => ({ time: t, value: x }));
  g.ema.setData(cizgi(v.ema)); g.ku.setData(cizgi(v.kanal_ust)); g.ka.setData(cizgi(v.kanal_alt));
  g.mum.setMarkers(v.isaretler.map((m) => ({ time: m.t, position: m.yon === "LONG" ? "belowBar" : "aboveBar",
    color: m.yon === "LONG" ? "#26a69a" : "#ef5350", shape: m.yon === "LONG" ? "arrowUp" : "arrowDown", text: m.yon === "LONG" ? "L" : "S" })));
  g.cizgiler.forEach((c) => g.mum.removePriceLine(c)); g.cizgiler = [];
  const ekle = (fiyat, renk, baslik) => { if (fiyat) g.cizgiler.push(g.mum.createPriceLine({ price: fiyat, color: renk, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: baslik })); };
  const a = v.aktif[0];
  if (a) { ekle(a.tur === "yaklasan" ? a.seviye : a.fiyat, "#8b98a5", a.tur === "yaklasan" ? "kırılım" : "giriş"); ekle(a.stop, "#f0b429", "stop"); ekle(a.likidasyon, "#ef5350", "likidasyon"); }
  try { const pz = await api("/api/pozisyonlar");
    pz.pozisyonlar.filter((p) => p.durum === "acik" && p.sembol === sembol).forEach((p) => {
      ekle(p.giris, "#c9d1d9", `poz #${p.id}`); ekle(p.stop, "#f0b429", "stop"); ekle(p.onerilen_stop, "#26a69a", "önerilen"); ekle(p.likidasyon, "#ef5350", "likid."); });
  } catch { /* yok */ }
  $("#grafikBilgi").textContent = `${v.sembol} · ${v.aralik === "1h" ? "1 saat" : "4 saat"} · EMA${v.ema_n}(4s) · kanal ${v.giris_n} · ATR ${fmt.f(v.atr)}`
    + (a ? ` · aktif: ${a.yon} (${a.tur === "yaklasan" ? "yaklaşan" : a.yeni ? "YENİ" : "devam"})` : "");
  if (!sessiz) g.chart.timeScale().fitContent();
  turevYukle(sembol);
}

// ------------------------------------------------------------------ türev verisi (grafik altı)
async function turevYukle(sembol) {
  const kap = $("#turevKutu");
  let v;
  try { v = await api(`/api/turev?sembol=${encodeURIComponent(sembol)}`); }
  catch { kap.replaceChildren(); $("#turevNot").textContent = ""; return; }
  if (!v.veri) { kap.replaceChildren(); $("#turevNot").textContent = "Türev verisi yok."; return; }
  const x = v.veri;
  const kart = (k, deger, ipucu, sinif) => el("div", { class: "kart", title: ipucu }, el("span", {}, k), el("b", { class: sinif || "" }, deger));
  kap.replaceChildren(
    kart("Açık pozisyon", fmt.usd(x.oi) + " $", "Binance USDT-M toplam açık pozisyon"),
    kart(`OI değişimi (${v.tf === "4h" ? "6×4s" : "6×1s"})`, fmt.y(x.oi_deg), "Pozitif: yeni pozisyon açılıyor", isaretSinif(x.oi_deg)),
    kart("Fonlama (son)", v.fonlama == null ? "-" : (v.fonlama * 100).toFixed(4) + "%", "8 saatlik; pozitif = long'lar öder"),
    kart("Long/short hesap", fmt.d(x.ls_hesap), "Tüm hesaplarda long/short oranı"),
    kart("Kalabalık (z)", fmt.d(x.ls_z), "> +1.5: long tarafı aşırı kalabalık; < −1.5: short kalabalık"),
    kart("Büyük trader L/S", fmt.d(x.top_ls), "En büyük hesapların pozisyon oranı"),
    kart("Taker alım/satım", fmt.d(x.taker), "> 1: agresif alıcılar baskın"));
  $("#turevNot").textContent = `Türev verisi: ${v.kaynak}. Son: ${fmt.zaman(v.zaman)}. Sinyale etkisi RAPOR.md'deki deneye göre belirlenir.`;
}

// ------------------------------------------------------------------ piyasa (CoinGecko / ısı haritası)
$$("#haritaDonem button").forEach((b) => b.addEventListener("click", () => { durum.haritaD = b.dataset.d; piyasaRotaYaz(); haritaCiz(); }));
$("#haritaVadeli").addEventListener("change", () => { piyasaRotaYaz(); haritaCiz(); });
function piyasaRotaYaz() {
  const p = new URLSearchParams({ d: durum.haritaD });
  if ($("#haritaVadeli").checked) p.set("vadeli", "1");
  rotaYaz("piyasa", p);
}

async function piyasaYukle() {
  let v;
  try { v = await api("/api/piyasa?n=100"); }
  catch (e) { $("#piyasaNot").textContent = "Piyasa verisi alınamadı: " + e.message; return; }
  durum.piyasa = v;
  const g = v.genel;
  const kart = (k, deger, sinif) => el("div", { class: "kart" }, el("span", {}, k), el("b", { class: sinif || "" }, deger));
  const yuzde = (x) => (x == null ? "-" : x.toFixed(1) + "%");
  $("#piyasaGenel").replaceChildren(...(g ? [
    kart("Toplam piyasa değeri", fmt.usd(g.toplam_piyasa_degeri) + " $"),
    kart("24s değişim", g.degisim_24s == null ? "-" : g.degisim_24s.toFixed(2) + "%", isaretSinif(g.degisim_24s)),
    kart("24s hacim", fmt.usd(g.toplam_hacim) + " $"),
    kart("BTC dominansı", yuzde(g.btc_dominans)),
    kart("ETH dominansı", yuzde(g.eth_dominans)),
    kart("Stabilcoin payı", yuzde(g.stabil_pay))] : [el("p", { class: "soluk" }, "Küresel veri yok (CoinGecko'ya ulaşılamadı).")]));
  $("#piyasaNot").textContent = `Isı haritası: ${v.harita_kaynak}; kutu boyu piyasa değeriyle, renk seçili dönemdeki değişimle orantılı. `
    + `Kaynaklar: CoinGecko ${v.kaynaklar.coingecko ? "✓" : "✗"}, CoinMarketCap ${v.kaynaklar.coinmarketcap ? "✓" : "anahtar yok"}, `
    + `CoinGlass ${v.kaynaklar.coinglass ? "✓" : "anahtar yok"}. ${v.not}`;
  haritaCiz();
}

function haritaCiz() {
  const v = durum.piyasa;
  if (!v) return;
  const d = durum.haritaD || "d24s";
  $$("#haritaDonem button").forEach((b) => b.classList.toggle("secili", b.dataset.d === d));
  let liste = v.isi_haritasi.filter((x) => !x.stabil && x.piyasa_degeri);
  if ($("#haritaVadeli").checked) liste = liste.filter((x) => x.vadeli);
  if (!liste.length) { $("#isiHaritasi").replaceChildren(el("p", { class: "harita-bos" }, "Gösterilecek veri yok.")); return; }
  const enb = Math.max(...liste.map((x) => Math.sqrt(x.piyasa_degeri)));
  const olcek = d === "d1s" ? 2 : d === "d24s" ? 8 : 20;
  const renk = (p) => {
    if (p == null) return "#5a6470";
    const k = Math.max(-1, Math.min(1, p / olcek));
    const a = 0.35 + 0.65 * Math.abs(k);
    return k >= 0 ? `rgba(38,166,154,${a})` : `rgba(239,83,80,${a})`;
  };
  $("#isiHaritasi").replaceChildren(...liste.map((x) => {
    const oran = Math.sqrt(x.piyasa_degeri) / enb;
    const k = el("div", { class: "karo" + (oran > 0.35 ? " buyuk" : ""), title: `${x.ad}: ${fmt.f(x.fiyat)} $`,
      onclick: () => { if (x.vadeli) location.hash = `#/grafik?sembol=${encodeURIComponent(x.sembol + "USDT")}`; } },
      el("b", {}, x.sembol), el("span", {}, x[d] == null ? "-" : (x[d] > 0 ? "+" : "") + x[d].toFixed(2) + "%"));
    k.style.flexBasis = Math.round(60 + 340 * oran) + "px";
    k.style.minHeight = Math.round(48 + 90 * oran) + "px";
    k.style.background = renk(x[d]);
    return k;
  }));
}

// ------------------------------------------------------------------ pozisyonlar
function pozisyonFormuDoldur(x) {
  const f = $("#pozForm");
  f.sembol.value = x.sembol; f.yon.value = x.yon; f.giris.value = x.fiyat; f.notional.value = x.notional.toFixed(2);
  f.adet.value = ""; f.kaldirac.value = x.kaldirac; f.stop.value = x.stop; f.sinyal_id.value = x.id || "";
  f.not_metni.value = `Sinyal ${fmt.zaman(x.zaman)} (${x.yeni ? "YENİ" : "devam"}) — giriş fiyatını gerçekleşen fiyatla güncelleyin`;
  location.hash = "#/pozisyonlar?form=1";
}

$("#pozForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target; $("#pozHata").textContent = "";
  const sayi = (v) => (v === "" ? null : Number(v));
  const g = { sembol: f.sembol.value.trim().toUpperCase(), yon: f.yon.value, giris: sayi(f.giris.value), adet: sayi(f.adet.value),
    notional: sayi(f.notional.value), kaldirac: sayi(f.kaldirac.value), stop: sayi(f.stop.value),
    sinyal_id: f.sinyal_id.value ? Number(f.sinyal_id.value) : null, not_metni: f.not_metni.value };
  try {
    await api("/api/pozisyonlar", { method: "POST", body: g });
    f.reset(); f.sinyal_id.value = ""; $("#pozFormKutu").open = false; toast("Pozisyon kaydedildi"); pozisyonlariYukle();
  } catch (err) { $("#pozHata").textContent = err.message; }
});

async function pozisyonlariYukle(p) {
  if (p && p.get("form")) $("#pozFormKutu").open = true;
  let v; try { v = await api("/api/pozisyonlar"); } catch { return; }
  const kap = $("#pozListe");
  if (!v.pozisyonlar.length) { kap.replaceChildren(el("p", { class: "soluk" }, "Kayıtlı pozisyon yok.")); return; }
  kap.replaceChildren(...v.pozisyonlar.map(pozisyonKarti));
}

function pozisyonKarti(p) {
  const acik = p.durum === "acik";
  const uyarilar = (p.degerlendirme || "").split(/(?<=\.|!)\s+/).filter(Boolean);
  return el("div", { class: `kart sinyal ${p.yon}` },
    el("div", { class: "ust-satir" },
      el("h3", {}, el("span", { class: "yon-" + p.yon }, p.yon), " ", p.sembol, " ", el("span", { class: "soluk" }, "#" + p.id)),
      el("span", { class: "etiket" + (acik ? " yeni" : "") }, acik ? "açık" : "kapalı")),
    el("div", { class: "izgara" },
      kv("Giriş", fmt.f(p.giris)), kv("Miktar", fmt.f(p.adet)), kv("Kaldıraç", fmt.d(p.kaldirac, 0) + "x"),
      kv(acik ? "Son fiyat" : "Kapanış", fmt.f(acik ? p.son_fiyat : p.kapanis_fiyat)),
      el("div", {}, el("span", {}, "K/Z"), el("b", { class: isaretSinif(p.pnl) }, fmt.d(p.pnl) + " $")),
      el("div", {}, el("span", {}, "R katı"), el("b", { class: isaretSinif(p.r) }, p.r == null ? "-" : fmt.d(p.r) + "R")),
      kv("Borsadaki stop", fmt.f(p.stop)), kv("Önerilen stop", fmt.f(p.onerilen_stop)), kv("Likidasyon", fmt.f(p.likidasyon))),
    acik ? uyarilar.map((u) => el("div", { class: "poz-uyari" + (/LİKİDASYON|ÇIKIŞ|geçti/.test(u) ? " ciddi" : "") }, u)) : null,
    p.not_metni ? el("p", { class: "soluk" }, "Not: " + p.not_metni) : null,
    el("div", { class: "filtre" },
      acik && p.onerilen_stop && p.onerilen_stop !== p.stop ? el("button", { class: "kucuk", onclick: () => stopGuncelle(p, p.onerilen_stop) }, "Stopu önerilene çektim") : null,
      acik ? el("button", { class: "kucuk ikincil", onclick: () => stopGuncelle(p) }, "Stop gir") : null,
      el("button", { class: "kucuk ikincil", onclick: () => notEkle(p) }, "Not"),
      acik ? el("button", { class: "kucuk ikincil", onclick: () => pozKapat(p) }, "Kapat") : null,
      el("button", { class: "kucuk tehlike", onclick: () => pozSil(p) }, "Sil"),
      el("button", { class: "kucuk ikincil", onclick: () => { location.hash = `#/grafik?sembol=${p.sembol}`; } }, "Grafik")));
}

async function stopGuncelle(p, deger) {
  const v = deger ?? Number(prompt(`${p.sembol} için borsada girdiğiniz yeni stop:`, p.onerilen_stop ?? p.stop));
  if (!v || !isFinite(v)) return;
  try { await api(`/api/pozisyonlar/${p.id}`, { method: "PATCH", body: { stop: v } }); toast("Stop güncellendi (borsada da girdiğinizden emin olun)"); pozisyonlariYukle(); }
  catch (e) { toast(e.message); }
}
async function notEkle(p) {
  const n = prompt("Not:", p.not_metni || ""); if (n === null) return;
  try { await api(`/api/pozisyonlar/${p.id}`, { method: "PATCH", body: { not_metni: n.slice(0, 1000) } }); pozisyonlariYukle(); } catch (e) { toast(e.message); }
}
async function pozKapat(p) {
  const f = Number(prompt("Kapanış fiyatı:", p.son_fiyat ?? p.giris)); if (!f || !isFinite(f)) return;
  try { await api(`/api/pozisyonlar/${p.id}/kapat`, { method: "POST", body: { fiyat: f } }); pozisyonlariYukle(); } catch (e) { toast(e.message); }
}
async function pozSil(p) {
  if (!confirm(`#${p.id} ${p.sembol} kaydı silinsin mi?`)) return;
  try { await api(`/api/pozisyonlar/${p.id}`, { method: "DELETE" }); pozisyonlariYukle(); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ tablo yardımcısı
function tablo(hedef, sutunlar, satirlar) {
  const t = $(hedef);
  const bas = el("thead", {}, el("tr", {}, sutunlar.map((s) => el("th", {}, s[0]))));
  const gov = el("tbody", {}, satirlar.map((r) => el("tr", {}, sutunlar.map(([, f, sinif]) => {
    const v = f(r); return el("td", { class: sinif ? sinif(r) : "" }, v); }))));
  t.replaceChildren(bas, gov);
  if (!satirlar.length) t.appendChild(el("tbody", {}, el("tr", {}, el("td", { colspan: sutunlar.length, class: "soluk" }, "Veri yok"))));
}

// ------------------------------------------------------------------ geçmiş
async function gecmisYukle() {
  let v; try { v = await api("/api/gecmis?limit=1000"); } catch { return; }
  const s = v.istatistik, bt = v.backtest;
  const satir = (ad, c, b) => [ad, c?.islem ?? 0, fmt.y(c?.kazanma), fmt.d(c?.ort_r, 3), fmt.d(c?.pf_r), b ? fmt.y(b.kazanma) : "-", b ? fmt.d(b.ort_r, 3) : "-", b ? fmt.d(b.pf_r) : "-"];
  const kap = $("#gecmisOzet");
  const t = el("table", {}, el("thead", {}, el("tr", {}, ["", "Canlı işlem", "Canlı kazanma", "Canlı ort. R", "Canlı PF", "Backtest kazanma", "Backtest ort. R", "Backtest PF"].map((x) => el("th", {}, x)))),
    el("tbody", {}, [satir("Genel", s.genel, bt?.genel), satir("LONG", s.long, bt?.long), satir("SHORT", s.short, bt?.short), satir("Yalnız YENİ", s.yeni, null)]
      .map((r) => el("tr", {}, r.map((x) => el("td", {}, x))))));
  let uyari = null;
  if (bt && s.genel.islem >= 30 && s.genel.ort_r < bt.genel.ort_r - 2 * 1.5 / Math.sqrt(s.genel.islem))
    uyari = el("p", { class: "uyari-kutu" }, "Canlı sonuçlar backtest beklentisinin belirgin şekilde altında. Strateji bozuluyor olabilir; pozisyon boyutunu küçültmeyi düşünün.");
  kap.replaceChildren(el("h3", {}, "Canlı sinyal sonuçları vs backtest beklentisi"),
    el("p", { class: "soluk" }, "Her sinyalin sonucu backtest ile aynı çıkış kurallarıyla (sonraki açılışta giriş, 3×ATR takip eden stop, karşı kanal) simüle edilir. "
      + (bt ? `Backtest: ${bt.demo ? "DEMO (sentetik) " : ""}rapor ${fmt.zaman(bt.kaynak)}, varyant ${bt.varyant} (sürüm ${bt.surum}). Canlı parametre sürümü: ${v.param_surum}`
        + (bt.eslesme ? " — eşleşiyor." : " — EŞLEŞMİYOR: canlı parametrelerin backtesti yok, karşılaştırma yaklaşıktır.") : "Backtest raporu yok (python tarayici.py backtest).")),
    el("div", { class: "tablo-kap" }, t), ...(uyari ? [uyari] : []));
  ileriTestYukle();
  tablo("#gecmisSembol", [["Sembol", (r) => r[0]], ["İşlem", (r) => r[1].islem], ["Kazanma", (r) => fmt.y(r[1].kazanma)],
    ["Ort. R", (r) => fmt.d(r[1].ort_r, 3), (r) => isaretSinif(r[1].ort_r)], ["Toplam R", (r) => fmt.d(r[1].toplam_r, 2)]],
    Object.entries(s.sembol).filter(([, x]) => x.islem));
  tablo("#gecmisTablo", [["Zaman", (r) => fmt.zaman(r.zaman)], ["Sembol", (r) => r.sembol], ["Yön", (r) => r.yon, (r) => "yon-" + r.yon],
    ["Etiket", (r) => (r.yeni ? "YENİ" : "devam")], ["Fiyat", (r) => fmt.f(r.fiyat)], ["Stop", (r) => fmt.f(r.stop)],
    ["Durum", (r) => r.durum], ["Çıkış", (r) => r.cikis_neden || "-"], ["Süre (s)", (r) => r.sure_saat ?? "-"],
    ["R", (r) => (r.r == null ? "-" : fmt.d(r.r)), (r) => isaretSinif(r.r)], ["Sürüm", (r) => r.param_surum]], v.sinyaller);
}

// ------------------------------------------------------------------ backtest
async function backtestYukle(varyant) {
  let v; try { v = await api("/api/backtest"); } catch { return; }
  const c = v.calisma || {};
  $("#btDurum").textContent = c.calisiyor ? `çalışıyor… ${c.son_satir || ""}` : c.kod != null ? `son çalışma kodu ${c.kod}` : "";
  $("#btCalistir").disabled = !!c.calisiyor;
  const rp = v.rapor;
  if (!rp) { $("#btBilgi").textContent = "Rapor yok. 'python tarayici.py backtest' çalıştırın veya butonu kullanın."; return; }
  durum.bt = rp;
  const adlar = Object.keys(rp.varyantlar);
  varyant = adlar.includes(varyant) ? varyant : (adlar.includes($("#btVaryant").value) ? $("#btVaryant").value : "temel");
  $("#btVaryant").replaceChildren(...adlar.map((a) => el("option", { value: a, selected: a === varyant }, a)));
  const vr = rp.varyantlar[varyant];
  $("#btBilgi").textContent = `${rp.demo ? "DEMO (sentetik veri) — " : ""}Oluşturma ${fmt.zaman(rp.olusturma)} · ${rp.veri.kaynak} · ${Object.keys(rp.veri.semboller).length} sembol · `
    + `risk %${rp.risk.risk_yuzde}, kaldıraç tavanı ${rp.risk.max_kaldirac}x, komisyon %${rp.maliyet.komisyon * 100}/yön, kayma %${rp.maliyet.kayma * 100}/yön, fonlama: ${rp.maliyet.fonlama_mod}. Seçili: ${vr.ozet_metin}`;
  tablo("#btVaryantlar", [["Varyant", (r) => r[0]], ["İşlem", (r) => r[1].ozet.havuz_r.islem], ["Kazanma", (r) => fmt.y(r[1].ozet.havuz_r.kazanma)],
    ["Ort. R", (r) => fmt.d(r[1].ozet.havuz_r.ort_r, 3), (r) => isaretSinif(r[1].ozet.havuz_r.ort_r)], ["PF(R)", (r) => fmt.d(r[1].ozet.havuz_r.pf_r)],
    ["Portföy", (r) => fmt.y(r[1].ozet.portfoy.toplam_getiri), (r) => isaretSinif(r[1].ozet.portfoy.toplam_getiri)],
    ["Yıllık", (r) => fmt.y(r[1].ozet.portfoy.yillik_getiri)], ["Max DD", (r) => fmt.y(r[1].ozet.portfoy.max_dusus)], ["Sharpe", (r) => fmt.d(r[1].ozet.portfoy.sharpe)],
    ["Kârlı sembol", (r) => fmt.y(r[1].ozet.karli_sembol_orani)], ["Holdout R", (r) => fmt.d(r[1].holdout?.r_ort_r, 3), (r) => isaretSinif(r[1].holdout?.r_ort_r)]],
    Object.entries(rp.varyantlar));
  // eğri
  const kap = $("#btGrafik");
  if (!durum.btGrafik) {
    const koyu = matchMedia("(prefers-color-scheme: dark)").matches;
    durum.btGrafik = LightweightCharts.createChart(kap, { autoSize: true, layout: { background: { color: "transparent" }, textColor: koyu ? "#c9d1d9" : "#1f2328" },
      grid: { vertLines: { visible: false }, horzLines: { color: koyu ? "#1f2a35" : "#eef1f4" } }, rightPriceScale: { mode: 1 } });
    durum.btSeri = {};
  }
  Object.values(durum.btSeri).forEach((s) => durum.btGrafik.removeSeries(s)); durum.btSeri = {};
  const renk = ["#4c9aff", "#f0883e", "#26a69a", "#ef5350", "#a371f7", "#f0b429", "#8b98a5", "#3fb950"];
  adlar.forEach((a, i) => { const s = durum.btGrafik.addLineSeries({ color: renk[i % renk.length], lineWidth: a === varyant ? 3 : 1, title: a, priceLineVisible: false });
    s.setData(rp.varyantlar[a].egri.map(([t, x]) => ({ time: t, value: x }))); durum.btSeri[a] = s; });
  durum.btGrafik.timeScale().fitContent();
  tablo("#btDilim", [["Dilim", (r) => r.dilim], ["İşlem", (r) => r.r_islem], ["Ort. R", (r) => fmt.d(r.r_ort_r, 3), (r) => isaretSinif(r.r_ort_r)],
    ["Toplam R", (r) => fmt.d(r.r_toplam_r, 1)], ["Kazanma", (r) => fmt.y(r.r_kazanma)], ["Long R", (r) => fmt.d(r.long_r, 1)], ["Short R", (r) => fmt.d(r.short_r, 1)],
    ["Portföy", (r) => fmt.y(r.portfoy_getiri), (r) => isaretSinif(r.portfoy_getiri)], ["DD", (r) => fmt.y(r.portfoy_dd)], ["Kârlı sembol", (r) => fmt.y(r.karli_sembol_orani)]], vr.dilimler);
  const iz = rp.izgara?.[varyant];
  $("#btIzgaraOzet").textContent = iz ? `${iz.ozet.kombinasyon} kombinasyon · ort. R > 0 oranı ${fmt.y(iz.ozet.karli_kombinasyon_orani_R)} · portföyü kârlı oranı ${fmt.y(iz.ozet.karli_kombinasyon_orani_portfoy)} · medyan ort. R ${fmt.d(iz.ozet.medyan_ort_r, 3)}` : "Bu varyant için ızgara yok.";
  tablo("#btIzgara", [["Giriş/Çıkış/ATR/EMA", (r) => `${r.param.giris_n}/${r.param.cikis_n}/${r.param.atr_kat}/${r.param.ema_n}`], ["İşlem", (r) => r.islem],
    ["Ort. R", (r) => fmt.d(r.ort_r, 3), (r) => isaretSinif(r.ort_r)], ["Kazanma", (r) => fmt.y(r.kazanma)], ["Portföy", (r) => fmt.y(r.portfoy_getiri), (r) => isaretSinif(r.portfoy_getiri)],
    ["Kârlı sembol", (r) => fmt.y(r.karli_sembol_orani)]], iz ? iz.liste.slice().sort((a, b) => b.ort_r - a.ort_r) : []);
  tablo("#btWF", [["Test yılı", (r) => r.test_yili], ["Eğitim", (r) => r.egitim], ["Seçilen", (r) => `${r.secilen.giris_n}/${r.secilen.cikis_n}/${r.secilen.atr_kat}/${r.secilen.ema_n}`],
    ["Eğitim R", (r) => fmt.d(r.egitim_ort_r, 3)], ["Test R", (r) => fmt.d(r.test_ort_r, 3), (r) => isaretSinif(r.test_ort_r)], ["Test işlem", (r) => r.test_islem],
    ["Varsayılan test R", (r) => fmt.d(r.varsayilan_test_ort_r, 3)], ["Yüzdelik", (r) => fmt.y(r.test_sirasi_yuzdelik, 0)]], rp.walk_forward?.[varyant] || []);
  tablo("#btSembol", [["Sembol", (r) => r.sembol], ["Başlangıç", (r) => r.baslangic], ["Toplam", (r) => fmt.y(r.toplam_getiri), (r) => isaretSinif(r.toplam_getiri)],
    ["Yıllık", (r) => fmt.y(r.yillik_getiri)], ["Max DD", (r) => fmt.y(r.max_dusus)], ["Sharpe", (r) => fmt.d(r.sharpe)], ["İşlem", (r) => r.islem],
    ["Kazanma", (r) => fmt.y(r.kazanma)], ["PF", (r) => fmt.d(r.profit_factor)], ["Ort. R", (r) => fmt.d(r.ort_r, 3)], ["Likid.", (r) => r.likidasyon], ["Al-tut", (r) => fmt.y(r.al_tut, 0)]], vr.semboller);
  const tv = v.turev;
  if (tv) {
    $("#btTurevNot").textContent = `Dönem ${tv.donem[0]} → ${tv.donem[1]} (türev verisi 2021-12'den beri). Kabul: tabandan daha yüksek ort. R, ≥4/5 yılda daha iyi, holdout'ta daha iyi, eşiklerin ≥2/3'ü daha iyi, işlem ≥ %40.`;
    const satirlar = [];
    for (const [tad, x] of Object.entries(tv.tabanlar)) {
      satirlar.push({ ad: `${tad} (taban)`, v: x.taban, k: null });
      for (const [fad, f] of Object.entries(x.filtreler)) satirlar.push({ ad: `${tad} ${fad}`, v: f, k: f.kriter });
    }
    tablo("#btTurev", [["Varyant", (r) => r.ad], ["İşlem", (r) => r.v.r.islem], ["Ort. R", (r) => fmt.d(r.v.r.ort_r, 3), (r) => isaretSinif(r.v.r.ort_r)],
      ["t", (r) => fmt.d(r.v.r.t, 1)], ["Holdout R", (r) => fmt.d(r.v.holdout.ort_r, 3), (r) => isaretSinif(r.v.holdout.ort_r)],
      ["Kârlı sembol", (r) => fmt.y(r.v.karli_sembol_orani)], ["Daha iyi yıl", (r) => (r.k ? `${r.v.yil_iyi}/5` : "-")],
      ["Kabul", (r) => (r.k ? (r.k.hepsi ? "✓" : "✗") : "-")]], satirlar);
  } else { $("#btTurevNot").textContent = "Deney çalıştırılmadı (python tarayici.py backtest --turev)."; tablo("#btTurev", [["-", () => "-"]], []); }
  const sg = (rp.saglik && (rp.saglik[varyant] || rp.saglik.temel)) || {};
  const sat = [];
  (sg.karistirilmis || []).forEach((x) => sat.push([`Karıştırılmış gerçek veri (tohum ${x.tohum})`, x.islem, x.ort_r]));
  if (sg.rastgele_yuruyus) sat.push([`Rastgele yürüyüş (medyan getiri ${fmt.y(sg.rastgele_yuruyus.medyan_getiri)})`, "-", sg.rastgele_yuruyus.ort_r]);
  Object.entries(sg.kaydirma || {}).forEach(([k, x]) => sat.push([{ "-1": "Sinyal 1 mum erken (gelecek bilgisi)", 0: "Normal", 1: "1 mum geç", 2: "2 mum geç" }[k], x.islem, x.ort_r]));
  Object.entries(sg.maliyet_duyarliligi || {}).forEach(([k, x]) => sat.push([`Maliyet: ${k}`, x.islem, x.ort_r]));
  const kr = rp.kriterler?.[varyant];
  $("#btKriter").textContent = kr ? `Ön kayıtlı canlı kriterleri: ${Object.entries(kr).filter(([k]) => k !== "hepsi").map(([k, x]) => `${k.split("_")[0]}${x === null ? "–" : x ? "✓" : "✗"}`).join(" ")} → ${kr.hepsi ? "GEÇTİ" : "GEÇMEDİ"}` : "";
  tablo("#btSaglik", [[`Test (${rp.saglik?.[varyant] ? varyant : "temel"})`, (r) => r[0]], ["İşlem", (r) => r[1]], ["Ort. R", (r) => fmt.d(r[2], 3), (r) => isaretSinif(r[2])]], sat);
}
$("#btVaryant").addEventListener("change", () => { rotaYaz("backtest", new URLSearchParams({ varyant: $("#btVaryant").value })); backtestYukle($("#btVaryant").value); });
$("#btCalistir").addEventListener("click", async () => {
  try { await api("/api/backtest/calistir", { method: "POST", body: { hizli: true } }); toast("Backtest başladı (arka planda)"); backtestYukle(); }
  catch (e) { toast(e.message); }
});
setInterval(() => { if (rota().ad === "backtest" && $("#btCalistir").disabled) backtestYukle(); }, 5000);

// ------------------------------------------------------------------ ayarlar
async function ayarlariYukle() {
  let v; try { v = await api("/api/ayarlar"); } catch { return; }
  const f = $("#ayarForm");
  for (const k of ["hesap", "risk_yuzde", "max_kaldirac", "sembol_sayisi"]) f[k].value = v[k];
  for (const k of ["telegram", "web_push", "zil"]) f[k].checked = !!v[k];
  $("#tgDurum").textContent = v.telegram_hazir ? "(TG_TOKEN/TG_CHAT tanımlı)" : "(TG_TOKEN ve TG_CHAT ortam değişkenleri tanımlı değil)";
  $("#pushAbone").disabled = !v.push_anahtar;
  $("#pushAbone").dataset.anahtar = v.push_anahtar || "";
  $("#cikisYap").classList.toggle("gizli", !v.parola_var);
}
$("#ayarForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const g = { hesap: Number(f.hesap.value), risk_yuzde: Number(f.risk_yuzde.value), max_kaldirac: Number(f.max_kaldirac.value),
    sembol_sayisi: Number(f.sembol_sayisi.value), telegram: f.telegram.checked, web_push: f.web_push.checked, zil: f.zil.checked };
  try { const r = await api("/api/ayarlar", { method: "POST", body: g }); $("#ayarMesaj").textContent = r.not; }
  catch (err) { $("#ayarMesaj").textContent = "Hata: " + err.message; }
});
$("#cikisYap").addEventListener("click", async () => { await api("/api/cikis", { method: "POST" }); location.reload(); });
$("#pushAbone").addEventListener("click", async () => {
  try {
    const anahtar = $("#pushAbone").dataset.anahtar;
    const kayit = await navigator.serviceWorker.ready;
    const izin = await Notification.requestPermission();
    if (izin !== "granted") { toast("Bildirim izni verilmedi"); return; }
    const b64 = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));
    const ab = await kayit.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(anahtar) });
    await api("/api/push/abone", { method: "POST", body: ab.toJSON() });
    toast("Web Push etkin");
  } catch (e) { toast("Web Push etkinleştirilemedi: " + e.message); }
});

// ------------------------------------------------------------------ telefona kurulum (PWA)
const kurulu = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const ios = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const mobil = () => /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent) || ios();
let kurIstegi = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  kurIstegi = e;
  $("#yukleDugme").classList.remove("gizli");
  $("#kurBandiDugme").classList.remove("gizli");
  kurBandiGoster();
});
async function uygulamayiYukle() {
  if (!kurIstegi) return;
  kurIstegi.prompt();
  const s = await kurIstegi.userChoice;
  if (s.outcome === "accepted") toast("Yüklendi: ana ekrandaki Vadeli simgesinden açabilirsiniz");
  kurIstegi = null;
  $("#yukleDugme").classList.add("gizli");
  $("#kurBandi").classList.add("gizli");
}
$("#yukleDugme").addEventListener("click", uygulamayiYukle);
$("#kurBandiDugme").addEventListener("click", uygulamayiYukle);
$("#kurBandiKapat").addEventListener("click", () => {
  $("#kurBandi").classList.add("gizli");
  try { localStorage.setItem("kurBandiKapali", "1"); } catch { /* özel mod */ }
});
window.addEventListener("appinstalled", () => $("#kurBandi").classList.add("gizli"));

function kurBandiGoster() {
  if (kurulu() || !mobil()) return;
  try { if (localStorage.getItem("kurBandiKapali")) return; } catch { /* yok */ }
  const guvenli = window.isSecureContext;
  $("#kurBandiMetin").textContent = !guvenli
    ? "Uygulama olarak kurmak için panoyu HTTPS adresinden açın (Ayarlar → Telefona kur)."
    : ios() ? "Uygulama gibi kullanmak için: Paylaş ⬆︎ → Ana Ekrana Ekle"
      : kurIstegi ? "Panoyu telefona uygulama olarak yükleyin." : "Tarayıcı menüsünden: Ana ekrana ekle";
  $("#kurBandi").classList.remove("gizli");
}

async function telefonKartiYukle() {
  let v;
  try { v = await api("/api/telefon"); } catch { return; }
  const qr = $("#telefonQr");
  if (v.url && v.qr_svg) {
    const img = el("img", { alt: "Telefon adresi QR kodu", src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(v.qr_svg) });
    qr.replaceChildren(img);
    $("#telefonUrl").textContent = v.url;
  } else {
    qr.replaceChildren();
    $("#telefonUrl").textContent = "Telefon adresi henüz yok.";
  }
  const parca = [];
  if (v.mesaj) parca.push(v.mesaj);
  if (!v.url) parca.push(`Bilgisayara Tailscale kurup giriş yapın (${v.indir}), sonra programı yeniden başlatın: adres ve QR kodu otomatik oluşur.`);
  if (kurulu()) parca.push("Bu cihazda uygulama olarak açık ✓");
  $("#telefonMesaj").textContent = parca.join(" ");
  if (v.onay_url) {
    $("#telefonMesaj").appendChild(el("a", { href: v.onay_url, target: "_blank", rel: "noopener" }, " HTTPS'i etkinleştirmek için tıklayın"));
  }
}

// ------------------------------------------------------------------ başlat
async function baslat() {
  try {
    const o = await api("/api/oturum");
    if (o.parola_gerekli && !o.giris_yapildi) { girisGoster(); return; }
  } catch { /* sunucu yok */ }
  $("#sekmeler").classList.remove("gizli");
  sseBaslat();
  kurBandiGoster();
  await sinyalleriYukle();
  ileriTestYukle();
  ekranGoster();
  setInterval(sinyalleriYukle, 60000); // SSE kaçırılırsa yedek
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
baslat();
