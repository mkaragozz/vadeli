/* Binance USDT-M herkese açık uç noktaları (API anahtarı YOK, emir YOK). Telefon doğrudan Binance'ten okur. */
const TABAN = "https://fapi.binance.com";

export class BinanceHatasi extends Error {
  constructor(mesaj, kod) { super(mesaj); this.kod = kod; }
}

const bekle = (ms) => new Promise((r) => setTimeout(r, ms));

async function al(yol, deneme = 4) {
  let gecikme = 1000;
  for (let i = 0; i < deneme; i++) {
    let r;
    try {
      r = await fetch(TABAN + yol, { cache: "no-store" });
    } catch (e) {
      if (i === deneme - 1) throw new BinanceHatasi("Binance'e ulaşılamadı. İnternet bağlantınızı kontrol edin.", "ag");
      await bekle(gecikme); gecikme *= 2; continue;
    }
    if (r.ok) return r.json();
    if (r.status === 451 || r.status === 403) {
      throw new BinanceHatasi("Binance bu konumdan vadeli veriye izin vermiyor (HTTP " + r.status + "). VPN açıksa kapatın.", "bolge");
    }
    if (r.status === 418 || r.status === 429) { // hız limiti: geri çekil
      const sn = Number(r.headers.get("Retry-After")) || 30;
      if (i === deneme - 1) throw new BinanceHatasi(`Binance hız limiti; ${sn} sn sonra tekrar deneyin.`, "limit");
      await bekle(sn * 1000); continue;
    }
    if (i === deneme - 1) throw new BinanceHatasi(`Binance hatası (HTTP ${r.status}).`, "http");
    await bekle(gecikme); gecikme *= 2;
  }
  return null;
}

/** Sınırlı eşzamanlılıkla çalıştır; tek sembol hatası diğerlerini durdurmaz. */
export async function havuz(liste, n, fn) {
  const sonuc = new Array(liste.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, liste.length) }, async () => {
    while (i < liste.length) {
      const k = i++;
      try { sonuc[k] = await fn(liste[k]); } catch (e) { sonuc[k] = e; }
    }
  }));
  return sonuc;
}

/** Hacme göre ilk n USDT-M perpetual (aktif). */
export async function evren(n) {
  const [bilgi, ticker] = await Promise.all([al("/fapi/v1/exchangeInfo"), al("/fapi/v1/ticker/24hr")]);
  const perp = new Set(bilgi.symbols.filter((s) => s.contractType === "PERPETUAL" && s.quoteAsset === "USDT"
    && s.marginAsset === "USDT" && s.status === "TRADING").map((s) => s.symbol));
  return ticker.filter((t) => perp.has(t.symbol))
    .map((t) => ({ sembol: t.symbol, hacim24: +t.quoteVolume, fiyat: +t.lastPrice, degisim: +t.priceChangePercent }))
    .sort((a, b) => b.hacim24 - a.hacim24).slice(0, n);
}

/** Yalnızca KAPANMIŞ mumlar: {t, o, h, l, c} dizileri. */
export async function mumlar(sembol, aralik = "4h", limit = 1000) {
  const ham = await al(`/fapi/v1/klines?symbol=${encodeURIComponent(sembol)}&interval=${aralik}&limit=${limit}`);
  const simdi = Date.now();
  const m = { t: [], o: [], h: [], l: [], c: [] };
  for (const k of ham) {
    if (k[6] >= simdi) continue; // kapanmamış mum hiçbir hesapta kullanılmaz
    m.t.push(k[0]); m.o.push(+k[1]); m.h.push(+k[2]); m.l.push(+k[3]); m.c.push(+k[4]);
  }
  return m;
}

/** Açık pozisyon (USDT) 5 dk anlık görüntüleri, son ~41 saat: [[ms, değer], ...] */
export async function acikPozisyon(sembol) {
  const ham = await al(`/futures/data/openInterestHist?symbol=${encodeURIComponent(sembol)}&period=5m&limit=500`);
  return ham.map((x) => [+x.timestamp, +x.sumOpenInterestValue]);
}

export async function fonlama(sembol) {
  const x = await al(`/fapi/v1/premiumIndex?symbol=${encodeURIComponent(sembol)}`);
  return { oran: +x.lastFundingRate, sonraki: +x.nextFundingTime };
}
