/* Vadeli Tarayıcı — telefon sürümü: strateji.
 * Python'daki vadeli/strateji.py `hazirla`, `risk_hesapla` ve canli.py `pozisyon_degerlendir`in birebir karşılığı.
 * Eşdeğerlik testi: vadeli-tarayici/tests/test_mobil_esdeger.py (aynı veride Python ile aynı sinyaller).
 *
 * Zaman kuralı: bar i = KAPANMIŞ mum. Kanal önceki N mumdan (shift 1). Sinyal kapanışta, giriş sonraki açılışta.
 */

export const VARSAYILAN = {
  tf: "4h", giris_n: 20, cikis_n: 10, atr_n: 14, atr_kat: 3, ema_n: 200,
  btc_filtre: true, oi_teyit: true, oi_n: 6,
  komisyon: 0.0005, kayma: 0.0003, mmr: 0.005, liq_oran: 0.5,
};
export const SURUM = "p8abf0564"; // Python StratejiParam(...).surum — backtest raporundaki varyantla aynı
export const TF_MS = { "1h": 3600000, "4h": 14400000 };

const nan = NaN;
const ok = (x) => x !== null && x !== undefined && !Number.isNaN(x);

export function ema(x, n) {
  // pandas ewm(span=n, adjust=False, min_periods=n)
  const a = 2 / (n + 1), out = new Array(x.length).fill(nan);
  let y = nan;
  for (let i = 0; i < x.length; i++) {
    y = i === 0 ? x[0] : a * x[i] + (1 - a) * y;
    if (i >= n - 1) out[i] = y;
  }
  return out;
}

export function atr(h, l, c, n) {
  // Wilder: ewm(alpha=1/n, adjust=False, min_periods=n) üzerinden gerçek aralık
  const a = 1 / n, out = new Array(c.length).fill(nan);
  let y = nan;
  for (let i = 0; i < c.length; i++) {
    const tr = i === 0 ? h[0] - l[0] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
    y = i === 0 ? tr : a * tr + (1 - a) * y;
    if (i >= n - 1) out[i] = y;
  }
  return out;
}

function kanal(x, n, enBuyuk) {
  // rolling(n).max/min().shift(1): bar i için i-n..i-1
  const out = new Array(x.length).fill(nan);
  for (let i = n; i < x.length; i++) {
    let v = x[i - n];
    for (let j = i - n + 1; j < i; j++) v = enBuyuk ? Math.max(v, x[j]) : Math.min(v, x[j]);
    out[i] = v;
  }
  return out;
}

/** Açık pozisyon anlık görüntüleri [[ms, oi], ...] → her tetik mumu için [T, T+tf) aralığındaki SON görüntü. */
export function oiHizala(zaman, anlik, tf) {
  const L = TF_MS[tf], out = new Array(zaman.length).fill(nan);
  if (!anlik || !anlik.length) return out;
  const s = anlik.slice().sort((p, q) => p[0] - q[0]);
  let j = 0;
  for (let i = 0; i < zaman.length; i++) {
    const bas = zaman[i], bit = bas + L;
    while (j < s.length && s[j][0] < bas) j++;
    let k = j, son = nan;
    while (k < s.length && s[k][0] < bit) { if (ok(s[k][1])) son = s[k][1]; k++; }
    out[i] = son > 0 ? son : nan; // 0 yazılmış açık pozisyon = veri yok (Python ile aynı)
  }
  return out;
}

/** mumlar: {t:[açılış ms], o,h,l,c}; btcRejim: Map(ms → -1/0/1) veya null; oi: oiHizala çıktısı veya null */
export function hazirla(m, p = VARSAYILAN, btcRejim = null, oi = null) {
  const n = m.c.length;
  const emaR = ema(m.c, p.ema_n);
  const rejim = m.c.map((c, i) => (!ok(emaR[i]) ? 0 : c > emaR[i] ? 1 : c < emaR[i] ? -1 : 0));
  const ku = kanal(m.h, p.giris_n, true), ka = kanal(m.l, p.giris_n, false);
  const cu = kanal(m.h, p.cikis_n, true), ca = kanal(m.l, p.cikis_n, false);
  const a = atr(m.h, m.l, m.c, p.atr_n);
  const oiDeg = new Array(n).fill(nan);
  if (oi) for (let i = p.oi_n; i < n; i++) oiDeg[i] = oi[i] / oi[i - p.oi_n] - 1;
  let btcSon = 0;
  const satir = [];
  for (let i = 0; i < n; i++) {
    const kl = ok(ku[i]) && m.c[i] > ku[i], ks = ok(ka[i]) && m.c[i] < ka[i];
    const lt = kl && rejim[i] === 1, st = ks && rejim[i] === -1;
    let fl = ok(a[i]), fs = ok(a[i]);
    if (p.btc_filtre) {
      if (btcRejim && btcRejim.has(m.t[i])) btcSon = btcRejim.get(m.t[i]);
      const b = btcRejim ? btcSon : 0;
      fl = fl && b === 1; fs = fs && b === -1;
    }
    if (p.oi_teyit) { const k = ok(oiDeg[i]) && oiDeg[i] > 0; fl = fl && k; fs = fs && k; }
    const ls = lt && fl, ss = st && fs;
    const once = satir[i - 1];
    const yarim = 0.5 * a[i];
    satir.push({
      t: m.t[i], o: m.o[i], h: m.h[i], l: m.l[i], c: m.c[i], ema: emaR[i], rejim: rejim[i],
      kanal_ust: ku[i], kanal_alt: ka[i], cikis_ust: cu[i], cikis_alt: ca[i], atr: a[i], oi_deg: oiDeg[i],
      long_tetik: lt, short_tetik: st, long_sinyal: ls, short_sinyal: ss,
      long_yeni: ls && !(once && once.long_tetik), short_yeni: ss && !(once && once.short_tetik),
      long_cikis: ok(ca[i]) && m.c[i] < ca[i], short_cikis: ok(cu[i]) && m.c[i] > cu[i],
      long_yakin: rejim[i] === 1 && !kl && ok(ku[i]) && ok(yarim) && ku[i] - m.c[i] <= yarim,
      short_yakin: rejim[i] === -1 && !ks && ok(ka[i]) && ok(yarim) && m.c[i] - ka[i] <= yarim,
    });
  }
  return satir;
}

export function likidasyon(giris, yon, k, mmr) {
  return yon === 1 ? giris * (1 - 1 / k + mmr) : giris * (1 + 1 / k - mmr);
}

/** Python risk_hesapla ile aynı: risk stop + iki yön maliyet dahil; kaldıraç stop ≤ likidasyon mesafesinin %50'si. */
export function riskHesapla(giris, stop, yon, r, p = VARSAYILAN) {
  const tek = p.komisyon + p.kayma;
  const d = Math.abs(giris - stop) / giris;
  const risk = r.hesap * r.risk_yuzde / 100;
  let notional = risk / (d + 2 * tek);
  const kLiq = 1 / (d / p.liq_oran + p.mmr);
  const k = Math.max(1, Math.min(r.max_kaldirac, Math.floor(kLiq)));
  notional = Math.min(notional, r.hesap * k * 0.95);
  const liq = likidasyon(giris, yon, k, p.mmr);
  const liqM = Math.abs(giris - liq) / giris;
  return { giris, stop, stop_yuzde: d * 100, kaldirac: k, notional, adet: notional / giris, teminat: notional / k,
    likidasyon: liq, liq_yuzde: liqM * 100, risk_usdt: notional * (d + 2 * tek) };
}

export function sonSinyaller(satir, r, p = VARSAYILAN) {
  const s = satir[satir.length - 1];
  const out = [];
  if (!s || !ok(s.atr)) return out;
  for (const [yon, ad, on] of [[1, "LONG", "long"], [-1, "SHORT", "short"]]) {
    const tur = s[`${on}_sinyal`] ? "sinyal" : s[`${on}_yakin`] ? "yaklasan" : null;
    if (!tur) continue;
    const seviye = tur === "sinyal" ? s.c : (yon === 1 ? s.kanal_ust : s.kanal_alt);
    const stop = seviye - yon * p.atr_kat * s.atr;
    out.push({ tur, yon: ad, zaman: s.t, fiyat: s.c, seviye, atr: s.atr, rejim: s.rejim, oi_deg: s.oi_deg,
      yeni: tur === "sinyal" ? s[`${on}_yeni`] : false, ...riskHesapla(seviye, stop, yon, r, p) });
  }
  return out;
}

/** Kullanıcının girdiği pozisyonu son kapanmış muma göre değerlendirir (Python pozisyon_degerlendir ile aynı kurallar). */
export function pozisyonDegerlendir(poz, satir, p = VARSAYILAN, mmr = VARSAYILAN.mmr) {
  const yon = poz.yon === "LONG" ? 1 : -1;
  const liq = likidasyon(poz.giris, yon, Math.max(1, poz.kaldirac), mmr);
  if (!satir || !satir.length) return { likidasyon: liq, notlar: ["Veri yok"] };
  const s = satir[satir.length - 1];
  const c = s.c, ilk = poz.ilk_stop || poz.stop;
  const pnl = yon * poz.adet * (c - poz.giris);
  const risk = Math.abs(poz.giris - ilk) * poz.adet;
  const L = TF_MS[p.tf];
  const acilisBar = Math.floor(poz.acilis / L) * L;
  let iz = c - yon * p.atr_kat * s.atr;
  const sonra = satir.filter((x) => x.t >= acilisBar && ok(x.atr));
  if (sonra.length) {
    const aday = sonra.map((x) => x.c - yon * p.atr_kat * x.atr);
    iz = yon === 1 ? Math.max(...aday) : Math.min(...aday);
  }
  const oneri = yon === 1 ? Math.max(poz.stop, iz) : Math.min(poz.stop, iz);
  const cikis = yon === 1 ? s.long_cikis : s.short_cikis;
  const stopKalan = (c - poz.stop) * yon, stopToplam = Math.abs(poz.giris - ilk);
  const liqKalan = (c - liq) * yon, liqToplam = Math.abs(poz.giris - liq);
  const notlar = [];
  if (stopKalan <= 0) notlar.push("Fiyat stop seviyesini geçti: borsadaki stop dolmuş olmalı, kontrol edin.");
  else if (stopKalan < 0.3 * stopToplam) notlar.push("Stop'a yakın (mesafenin %30'undan az kaldı).");
  if (liqKalan < 0.3 * liqToplam) notlar.push("LİKİDASYONA YAKIN!");
  if (cikis) notlar.push(`ÇIKIŞ SİNYALİ: ${p.cikis_n} mumluk karşı kanal kırıldı (sonraki açılışta çıkış).`);
  const stopDegisti = (oneri - poz.stop) * yon > Math.abs(poz.stop) * 1e-6; // küsurat farkını yok say
  if (stopDegisti) notlar.push(`Stopu ${+oneri.toPrecision(6)} seviyesine çekin.`);
  return { son_fiyat: c, stop_degisti: stopDegisti, pnl, r: risk > 0 ? pnl / risk : null, onerilen_stop: oneri, likidasyon: liq, cikis,
    notlar: notlar.length ? notlar : ["Normal."], zaman: s.t };
}
