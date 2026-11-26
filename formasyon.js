/* Formasyon, destek/direnç ve indikatör sinyalleri — Python vadeli/formasyon.py `sinyaller`, `seviye_hedefleri`, `trend`in
 * birebir karşılığı (eşdeğerlik testi: tests/test_formasyon_js.py). Telefon ve bilgisayar panosu ortak kullanır.
 * Girdi: kapanmış mumlar {o,h,l,c,v} (v = USDT hacmi). Sinyal satır i'nin kapanışında bilinir; giriş i+1 açılışında.
 */
import { ema, atr } from "./strateji.js";

export const K_PIVOT = 5, STOP_ATR = 1.5;
const nan = NaN;

export const AD = {
  yutan: "Yutan (engulfing)", cekic: "Çekiç / Asılı adam", ters_cekic: "Ters çekiç / Kayan yıldız",
  doji: "Yusufçuk / Mezar taşı doji", yildiz: "Sabah / Akşam yıldızı", uc_asker: "Üç beyaz asker / Üç kara karga",
  delen: "Delen çizgi / Kara bulut", harami: "Harami", marubozu: "Marubozu",
  ikili: "İkili dip / İkili tepe", obo: "Ters OBO / OBO", ucgen: "Üçgen kırılımı", bayrak: "Bayrak",
  dd_kirilim: "Destek/direnç kırılımı", dd_kirilim_hacim: "Destek/direnç kırılımı + hacim",
  rsi: "RSI 30/70 dönüşü", macd: "MACD kesişimi", ema_kesisim: "EMA20/50 kesişimi", bollinger: "Bollinger dönüşü",
  donchian: "Donchian 20 kırılımı",
};
export const AILE = { yutan: "mum", cekic: "mum", ters_cekic: "mum", doji: "mum", yildiz: "mum", uc_asker: "mum", delen: "mum",
  harami: "mum", marubozu: "mum", ikili: "grafik", obo: "grafik", ucgen: "grafik", bayrak: "grafik", dd_kirilim: "dd",
  dd_kirilim_hacim: "dd", rsi: "indikator", macd: "indikator", ema_kesisim: "indikator", bollinger: "indikator", donchian: "indikator" };

// ------------------------------------------------------------------ yardımcılar (pandas ile aynı)
function ewmAlpha(x, a, minP) { // ewm(alpha, adjust=False, min_periods) — baştaki NaN'lar atlanır
  const out = new Array(x.length).fill(nan);
  let y = nan, say = 0;
  for (let i = 0; i < x.length; i++) {
    if (Number.isNaN(x[i])) { if (say) out[i] = say >= minP ? y : nan; continue; }
    y = say === 0 ? x[i] : a * x[i] + (1 - a) * y;
    say++;
    if (say >= minP) out[i] = y;
  }
  return out;
}
function rolling(x, n, f) {
  const out = new Array(x.length).fill(nan);
  for (let i = n - 1; i < x.length; i++) out[i] = f(x.slice(i - n + 1, i + 1));
  return out;
}
const ort = (a) => a.reduce((s, v) => s + v, 0) / a.length;
const sapma = (a) => { const m = ort(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1)); };
const kaydir = (x, k = 1, dolgu = nan) => x.map((_, i) => (i >= k ? x[i - k] : dolgu));

export function rsi(c, n = 14) {
  const up = c.map((v, i) => (i === 0 ? nan : Math.max(v - c[i - 1], 0)));
  const dn = c.map((v, i) => (i === 0 ? nan : Math.max(c[i - 1] - v, 0)));
  const u = ewmAlpha(up, 1 / n, n), d = ewmAlpha(dn, 1 / n, n);
  return u.map((v, i) => (d[i] === 0 || Number.isNaN(d[i]) ? nan : 100 - 100 / (1 + v / d[i])));
}

export function pivotlar(h, l, k = K_PIVOT) {
  const n = h.length, pt = new Array(n).fill(false), pd = new Array(n).fill(false);
  for (let i = k; i < n - k; i++) {
    let mx = -Infinity, mn = Infinity;
    for (let j = i - k; j <= i + k; j++) { if (h[j] > mx) mx = h[j]; if (l[j] < mn) mn = l[j]; }
    pt[i] = h[i] >= mx; pd[i] = l[i] <= mn;
  }
  return [pt, pd];
}

export function trend(c) {
  const e20 = ema(c, 20), e50 = ema(c, 50);
  return c.map((v, i) => (Number.isNaN(e50[i]) ? 0 : v > e50[i] && e20[i] > e50[i] ? 1 : v < e50[i] && e20[i] < e50[i] ? -1 : 0));
}

// ------------------------------------------------------------------ sinyaller
export function sinyaller(m) {
  const { o, h, l, c, v } = m, n = c.length;
  const a = atr(h, l, c, 14);
  const govde = c.map((x, i) => Math.abs(x - o[i]));
  const aralik = c.map((_, i) => Math.max(h[i] - l[i], 1e-12));
  const ustF = c.map((x, i) => h[i] - Math.max(o[i], x)), altF = c.map((x, i) => Math.min(o[i], x) - l[i]);
  const yesil = c.map((x, i) => x > o[i]), kirmizi = c.map((x, i) => x < o[i]);
  const sma10 = rolling(c, 10, ort);
  const dusus = c.map((x, i) => x < sma10[i]), yuk = c.map((x, i) => x > sma10[i]);
  const o1 = kaydir(o), c1 = kaydir(c), o2 = kaydir(o, 2), c2 = kaydir(c, 2);
  const g1 = c1.map((x, i) => Math.abs(x - o1[i])), g2 = c2.map((x, i) => Math.abs(x - o2[i]));
  const d1 = kaydir(dusus, 1, false), y1 = kaydir(yuk, 1, false), d2 = kaydir(dusus, 2, false), y2 = kaydir(yuk, 2, false);
  const ar1 = kaydir(aralik);
  const S = {};
  const her = (f) => c.map((_, i) => !!f(i));
  S.yutan = [her((i) => d1[i] && c1[i] < o1[i] && yesil[i] && o[i] <= c1[i] && c[i] >= o1[i] && govde[i] > g1[i]),
    her((i) => y1[i] && c1[i] > o1[i] && kirmizi[i] && o[i] >= c1[i] && c[i] <= o1[i] && govde[i] > g1[i])];
  const kg = her((i) => govde[i] <= 0.35 * aralik[i]);
  S.cekic = [her((i) => d1[i] && kg[i] && altF[i] >= 2 * govde[i] && ustF[i] <= 0.25 * aralik[i]),
    her((i) => y1[i] && kg[i] && altF[i] >= 2 * govde[i] && ustF[i] <= 0.25 * aralik[i])];
  S.ters_cekic = [her((i) => d1[i] && kg[i] && ustF[i] >= 2 * govde[i] && altF[i] <= 0.25 * aralik[i]),
    her((i) => y1[i] && kg[i] && ustF[i] >= 2 * govde[i] && altF[i] <= 0.25 * aralik[i])];
  const doji = her((i) => govde[i] <= 0.1 * aralik[i]);
  S.doji = [her((i) => d1[i] && doji[i] && altF[i] >= 0.6 * aralik[i]), her((i) => y1[i] && doji[i] && ustF[i] >= 0.6 * aralik[i])];
  const ok = her((i) => g1[i] <= 0.3 * Math.max(g2[i], 1e-12));
  S.yildiz = [her((i) => d2[i] && c2[i] < o2[i] && ok[i] && yesil[i] && c[i] > (o2[i] + c2[i]) / 2),
    her((i) => y2[i] && c2[i] > o2[i] && ok[i] && kirmizi[i] && c[i] < (o2[i] + c2[i]) / 2)];
  const buyuk = her((i) => govde[i] >= 0.5 * aralik[i]);
  const ye1 = kaydir(yesil, 1, false), ye2 = kaydir(yesil, 2, false), ki1 = kaydir(kirmizi, 1, false), ki2 = kaydir(kirmizi, 2, false);
  const b1 = kaydir(buyuk, 1, false), b2 = kaydir(buyuk, 2, false);
  S.uc_asker = [her((i) => yesil[i] && ye1[i] && ye2[i] && buyuk[i] && b1[i] && b2[i] && c[i] > c1[i] && c1[i] > c2[i]),
    her((i) => kirmizi[i] && ki1[i] && ki2[i] && buyuk[i] && b1[i] && b2[i] && c[i] < c1[i] && c1[i] < c2[i])];
  S.delen = [her((i) => d1[i] && c1[i] < o1[i] && g1[i] >= 0.5 * ar1[i] && yesil[i] && o[i] <= c1[i] && c[i] > (o1[i] + c1[i]) / 2 && c[i] < o1[i]),
    her((i) => y1[i] && c1[i] > o1[i] && g1[i] >= 0.5 * ar1[i] && kirmizi[i] && o[i] >= c1[i] && c[i] < (o1[i] + c1[i]) / 2 && c[i] > o1[i])];
  const ic = her((i) => Math.min(o[i], c[i]) >= Math.min(o1[i], c1[i]) && Math.max(o[i], c[i]) <= Math.max(o1[i], c1[i]) && govde[i] < 0.5 * g1[i]);
  S.harami = [her((i) => d1[i] && c1[i] < o1[i] && yesil[i] && ic[i]), her((i) => y1[i] && c1[i] > o1[i] && kirmizi[i] && ic[i])];
  S.marubozu = [her((i) => yesil[i] && govde[i] >= 0.95 * aralik[i] && aralik[i] >= a[i]),
    her((i) => kirmizi[i] && govde[i] >= 0.95 * aralik[i] && aralik[i] >= a[i])];
  // indikatörler
  const r = rsi(c), r1 = kaydir(r);
  S.rsi = [her((i) => r1[i] < 30 && r[i] >= 30), her((i) => r1[i] > 70 && r[i] <= 70)];
  const e12 = ema(c, 12), e26 = ema(c, 26), mm = c.map((_, i) => e12[i] - e26[i]);
  const sig = ewmAlpha(mm, 2 / 10, 9), fark = mm.map((x, i) => x - sig[i]), f1 = kaydir(fark);
  S.macd = [her((i) => f1[i] < 0 && fark[i] >= 0), her((i) => f1[i] > 0 && fark[i] <= 0)];
  const e20 = ema(c, 20), e50 = ema(c, 50), kk = c.map((_, i) => e20[i] - e50[i]), k1 = kaydir(kk);
  S.ema_kesisim = [her((i) => k1[i] < 0 && kk[i] >= 0), her((i) => k1[i] > 0 && kk[i] <= 0)];
  const bo = rolling(c, 20, ort), bs = rolling(c, 20, sapma);
  const altB = bo.map((x, i) => x - 2 * bs[i]), ustB = bo.map((x, i) => x + 2 * bs[i]), altB1 = kaydir(altB), ustB1 = kaydir(ustB);
  S.bollinger = [her((i) => c1[i] < altB1[i] && c[i] > altB[i]), her((i) => c1[i] > ustB1[i] && c[i] < ustB[i])];
  const du = kaydir(rolling(h, 20, (x) => Math.max(...x))), da = kaydir(rolling(l, 20, (x) => Math.min(...x)));
  const du1 = kaydir(du), da1 = kaydir(da);
  S.donchian = [her((i) => c[i] > du[i] && !(c1[i] > du1[i])), her((i) => c[i] < da[i] && !(c1[i] < da1[i]))];
  Object.assign(S, ddVeGrafik(o, h, l, c, v, a));
  return S;
}

function ddVeGrafik(o, h, l, c, v, a) {
  const n = c.length, [pt, pdp] = pivotlar(h, l), K = K_PIVOT;
  const hacimOrt = kaydir(rolling(v, 20, ort));
  const bos = () => [new Array(n).fill(false), new Array(n).fill(false)];
  const out = { dd_kirilim: bos(), dd_kirilim_hacim: bos(), ikili: bos(), obo: bos(), ucgen: bos(), bayrak: null };
  const tepeler = [], dipler = [];
  let direnc = nan, destek = nan;
  let f = { ikiliAl: null, ikiliSat: null, oboAl: null, oboSat: null, ucgenAl: null, ucgenSat: null };
  for (let i = 0; i < n; i++) {
    const j = i - K;
    if (j >= 0) {
      if (pt[j]) { tepeler.push([j, h[j]]); direnc = h[j]; }
      if (pdp[j]) { dipler.push([j, l[j]]); destek = l[j]; }
      if ((pt[j] || pdp[j]) && tepeler.length >= 2 && dipler.length >= 2 && !Number.isNaN(a[i])) f = formasyonlar(tepeler, dipler, a[i], i, f);
    }
    if (i === 0) continue;
    const hacOk = !Number.isNaN(hacimOrt[i]) && v[i] > 1.5 * hacimOrt[i];
    if (!Number.isNaN(direnc) && c[i] > direnc && c[i - 1] <= direnc) { out.dd_kirilim[0][i] = true; out.dd_kirilim_hacim[0][i] = hacOk; direnc = nan; }
    if (!Number.isNaN(destek) && c[i] < destek && c[i - 1] >= destek) { out.dd_kirilim[1][i] = true; out.dd_kirilim_hacim[1][i] = hacOk; destek = nan; }
    for (const [ad, k] of [["ikili", f.ikiliAl], ["obo", f.oboAl], ["ucgen", f.ucgenAl]])
      if (k && i <= k[1] && c[i] > k[0] && c[i - 1] <= k[0]) out[ad][0][i] = true;
    for (const [ad, k] of [["ikili", f.ikiliSat], ["obo", f.oboSat], ["ucgen", f.ucgenSat]])
      if (k && i <= k[1] && c[i] < k[0] && c[i - 1] >= k[0]) out[ad][1][i] = true;
    if (f.ikiliAl && c[i] > f.ikiliAl[0]) f.ikiliAl = null;
    if (f.ikiliSat && c[i] < f.ikiliSat[0]) f.ikiliSat = null;
    if (f.oboAl && c[i] > f.oboAl[0]) f.oboAl = null;
    if (f.oboSat && c[i] < f.oboSat[0]) f.oboSat = null;
    if (f.ucgenAl && c[i] > f.ucgenAl[0]) { f.ucgenAl = null; f.ucgenSat = null; }
    if (f.ucgenSat && c[i] < f.ucgenSat[0]) { f.ucgenAl = null; f.ucgenSat = null; }
  }
  out.bayrak = bayrak(h, l, c, a);
  return out;
}

function formasyonlar(tepeler, dipler, a, i, f) {
  f = { ...f };
  const tol = 0.5 * a, gec = i + 50;
  const [[t1i, t1], [t2i, t2]] = tepeler.slice(-2), [[d1i, d1], [d2i, d2]] = dipler.slice(-2);
  const aradaDip = dipler.filter(([j]) => t1i < j && j < t2i).map((x) => x[1]);
  if (Math.abs(t1 - t2) <= tol && t2i - t1i >= 5 && aradaDip.length) f.ikiliSat = [Math.min(...aradaDip), gec];
  const aradaTepe = tepeler.filter(([j]) => d1i < j && j < d2i).map((x) => x[1]);
  if (Math.abs(d1 - d2) <= tol && d2i - d1i >= 5 && aradaTepe.length) f.ikiliAl = [Math.max(...aradaTepe), gec];
  if (tepeler.length >= 3) {
    const [[s1i, s1], [, b], [s2i, s2]] = tepeler.slice(-3);
    const dl = dipler.filter(([j]) => s1i < j && j < s2i).map((x) => x[1]);
    if (b > s1 + tol && b > s2 + tol && Math.abs(s1 - s2) <= 2 * tol && dl.length >= 2) f.oboSat = [Math.min(...dl), gec];
  }
  if (dipler.length >= 3) {
    const [[s1i, s1], [, b], [s2i, s2]] = dipler.slice(-3);
    const tl = tepeler.filter(([j]) => s1i < j && j < s2i).map((x) => x[1]);
    if (b < s1 - tol && b < s2 - tol && Math.abs(s1 - s2) <= 2 * tol && tl.length >= 2) f.oboAl = [Math.max(...tl), gec];
  }
  const duzT = Math.abs(t1 - t2) <= tol, duzD = Math.abs(d1 - d2) <= tol, alcT = t2 < t1 - tol, yukD = d2 > d1 + tol;
  if (duzT && yukD) f.ucgenAl = [Math.max(t1, t2), gec];
  else if (duzD && alcT) f.ucgenSat = [Math.min(d1, d2), gec];
  else if (alcT && yukD) { f.ucgenAl = [t2, gec]; f.ucgenSat = [d2, gec]; }
  return f;
}

function bayrak(h, l, c, a) {
  const n = c.length, al = new Array(n).fill(false), sat = new Array(n).fill(false);
  for (let i = 30; i < n; i++) {
    if (Number.isNaN(a[i])) continue;
    for (const w of [5, 10, 15]) {
      const bas = i - w, dirBas = bas - 10;
      if (dirBas < 0) continue;
      const direk = c[bas - 1] - c[dirBas];
      let kh = -Infinity, kl = Infinity;
      for (let j = bas; j < i; j++) { if (h[j] > kh) kh = h[j]; if (l[j] < kl) kl = l[j]; }
      if (Math.abs(direk) < 4 * a[bas - 1] || kh - kl > 0.5 * Math.abs(direk)) continue;
      if (direk > 0 && c[i] > kh && c[i - 1] <= kh) al[i] = true;
      else if (direk < 0 && c[i] < kl && c[i - 1] >= kl) sat[i] = true;
    }
  }
  return [al, sat];
}

// ------------------------------------------------------------------ seviyeler ve hedefler (son mum için)
/** Son mum i için seviye tabanlı hedef/stop (Python seviye_hedefleri ile aynı). Giriş bilinmediği için referans = son kapanış. */
export function seviyeHedefi(m, i, yon, giris) {
  const { h, l, c } = m, a = atr(h, l, c, 14)[i];
  if (Number.isNaN(a)) return null;
  const [pt, pdp] = pivotlar(h, l);
  const tf = [], dfv = [];
  for (let j = Math.max(0, i - 200); j <= i - K_PIVOT; j++) { if (pt[j]) tf.push(h[j]); if (pdp[j]) dfv.push(l[j]); }
  let hedef = nan, stop;
  if (yon === 1) {
    const ust = tf.filter((x) => x >= giris + a), alt = dfv.filter((x) => x <= giris - 0.5 * a);
    hedef = ust.length ? Math.min(...ust) : nan;
    stop = Math.max(alt.length ? Math.max(...alt) - 0.25 * a : giris - STOP_ATR * a, giris - 3 * a);
  } else {
    const alt = dfv.filter((x) => x <= giris - a), ust = tf.filter((x) => x >= giris + 0.5 * a);
    hedef = alt.length ? Math.max(...alt) : nan;
    stop = Math.min(ust.length ? Math.min(...ust) + 0.25 * a : giris + STOP_ATR * a, giris + 3 * a);
  }
  return { hedef: Number.isNaN(hedef) ? null : hedef, stop, atr: a };
}

/** Destek/direnç önerisi: son 200 mumdaki onaylı pivotlar, 0.5×ATR içindekiler tek seviyede birleştirilir. */
export function seviyeler(m, adet = 3) {
  const { h, l, c } = m, n = c.length, i = n - 1;
  const a = atr(h, l, c, 14)[i];
  if (Number.isNaN(a)) return { direncler: [], destekler: [], atr: nan };
  const [pt, pdp] = pivotlar(h, l);
  const ham = [];
  for (let j = Math.max(0, i - 200); j <= i - K_PIVOT; j++) {
    if (pt[j]) ham.push({ fiyat: h[j], j, tur: "tepe" });
    if (pdp[j]) ham.push({ fiyat: l[j], j, tur: "dip" });
  }
  ham.sort((p, q) => p.fiyat - q.fiyat);
  const kume = [];
  for (const x of ham) {
    const son = kume[kume.length - 1];
    if (son && x.fiyat - son.ust <= 0.5 * a) { son.uyeler.push(x); son.ust = x.fiyat; }
    else kume.push({ uyeler: [x], ust: x.fiyat });
  }
  const sev = kume.map((k) => ({ fiyat: ort(k.uyeler.map((x) => x.fiyat)), dokunma: k.uyeler.length,
    son_j: Math.max(...k.uyeler.map((x) => x.j)) }));
  const fiyat = c[i];
  const direncler = sev.filter((s) => s.fiyat > fiyat).sort((p, q) => p.fiyat - q.fiyat).slice(0, adet);
  const destekler = sev.filter((s) => s.fiyat < fiyat).sort((p, q) => q.fiyat - p.fiyat).slice(0, adet);
  for (const s of [...direncler, ...destekler]) { s.uzaklik = s.fiyat / fiyat - 1; s.mum_once = i - s.son_j; }
  return { direncler, destekler, atr: a, fiyat };
}
