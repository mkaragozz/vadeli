/* Skor (TabPFN ailesi araştırması, DENEYLER.md §9) — telefon ve pano ortak.
 * 1) `ozellikler`: Python vadeli/meta.py `ozellikler` ile aynı özellikleri SON kapanmış mum için hesaplar.
 * 2) `agacTahmin`: LightGBM "öğrenci" modelini (meta_model.json, dump_model biçimi) çalıştırır → olasılık.
 * Öğrenci, bilgisayarda çalışan büyük modelin (TabICL/TabDPT/Mitra) skorlarına damıtılmıştır; telefon modeli çalıştırmaz.
 */
import { ema, atr } from "./strateji.js";
import * as F from "./formasyon.js";

export const OZELLIK = ["rsi", "trend", "trend_ust", "atr_oran", "g5", "g20", "g60", "hacim_oran", "direnc_atr", "destek_atr",
  "kanal_konum", "btc_trend", "btc_g20", "zirveden"];
export const SINYAL_KOD = Object.fromEntries(Object.keys(F.AD).map((k, i) => [k, i]));
const nan = NaN;

/** m: {t,o,h,l,c,v} (kapanmış mumlar), ust: üst zaman dilimi mumları veya null, btc: BTC aynı zaman dilimi veya null,
 *  tfMs / ustMs: mum süreleri (ms). Döner: {ad: değer} (NaN = bilinmiyor). */
export function ozellikler(m, ust, btc, tfMs, ustMs) {
  const n = m.c.length, i = n - 1, c = m.c;
  const a = atr(m.h, m.l, c, 14);
  const r = F.rsi(c);
  const tr = F.trend(c);
  const out = {};
  out.rsi = r[i];
  out.trend = tr[i];
  out.trend_ust = nan;
  if (ust && ust.c.length > 60) {      // yalnız TAMAMLANMIŞ üst mum (kapanışı ≤ bu mumun kapanışı)
    const tu = F.trend(ust.c), kap = m.t[i] + tfMs;
    for (let j = ust.t.length - 1; j >= 0; j--) if (ust.t[j] + ustMs <= kap) { out.trend_ust = tu[j]; break; }
  }
  out.atr_oran = a[i] / c[i];
  for (const k of [5, 20, 60]) out["g" + k] = i >= k ? c[i] / c[i - k] - 1 : nan;
  let hs = 0; for (let j = i - 20; j < i; j++) hs += m.v[j];
  out.hacim_oran = i >= 20 && hs > 0 ? m.v[i] / (hs / 20) : nan;
  // en yakın onaylı pivot tepe (üstte) / dip (altta), son 200 mum, ATR cinsinden, en çok 10
  const [pt, pd] = F.pivotlar(m.h, m.l);
  let ust1 = Infinity, alt1 = -Infinity;
  for (let j = Math.max(0, i - 200); j <= i - F.K_PIVOT; j++) {
    if (pt[j] && m.h[j] > c[i] && m.h[j] < ust1) ust1 = m.h[j];
    if (pd[j] && m.l[j] < c[i] && m.l[j] > alt1) alt1 = m.l[j];
  }
  out.direnc_atr = a[i] > 0 ? Math.min(isFinite(ust1) ? (ust1 - c[i]) / a[i] : 10, 10) : nan;
  out.destek_atr = a[i] > 0 ? Math.min(isFinite(alt1) ? (c[i] - alt1) / a[i] : 10, 10) : nan;
  let hi = -Infinity, lo = Infinity;
  for (let j = i - 19; j <= i; j++) { hi = Math.max(hi, m.h[j]); lo = Math.min(lo, m.l[j]); }
  out.kanal_konum = hi > lo ? (c[i] - lo) / (hi - lo) : nan;
  out.btc_trend = nan; out.btc_g20 = nan;
  if (btc && btc.c.length > 60) {
    const k = btc.t.indexOf(m.t[i]);
    if (k >= 0) { out.btc_trend = F.trend(btc.c)[k]; out.btc_g20 = k >= 20 ? btc.c[k] / btc.c[k - 20] - 1 : nan; }
  }
  if (i >= 249) { let z = -Infinity; for (let j = i - 249; j <= i; j++) z = Math.max(z, c[j]); out.zirveden = c[i] / z - 1; }
  else out.zirveden = nan;
  for (const k of Object.keys(out)) if (!isFinite(out[k])) out[k] = nan;
  return out;
}

// ------------------------------------------------------------------ LightGBM ağaçları (kompakt biçim, vadeli/meta.py _kompakt)
// Yaprak = sayı; iç düğüm = [özellik, eşik, varsayılan_sol, eksik_tür(0 yok, 1 NaN, 2 sıfır), sol, sağ]
function dugum(d, x) {
  while (typeof d !== "number") {
    const [f, esik, vsol, mt, sol, sag] = d;
    const v = x[f];
    let git;
    // LightGBM: eksik tür "NaN" → varsayılan yön; "Zero" → 0 ve NaN varsayılan yöne; "None" → NaN, 0 sayılır
    if (Number.isNaN(v)) git = mt === 0 ? 0 <= esik : vsol;
    else if (mt === 2 && v === 0) git = vsol;
    else git = v <= esik;
    d = git ? sol : sag;
  }
  return d;
}

/** model: {sutunlar:[...], agaclar:[...]}; x: {ad: değer}. Döner olasılık (0-1). */
export function agacTahmin(model, x) {
  const v = model.sutunlar.map((k) => (x[k] === undefined || x[k] === null ? nan : x[k]));
  let s = 0;
  for (const t of model.agaclar) s += dugum(t, v);
  return 1 / (1 + Math.exp(-s));
}
