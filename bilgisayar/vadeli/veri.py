"""Veri katmanı: Binance USDT-M mumları ve fonlama oranları.

Kaynaklar (yalnızca herkese açık uç noktalar, API anahtarı YOK):
  * Binance resmi veri arşivi  https://data.binance.vision  (aylık/günlük ZIP, toplu geçmiş için hızlı)
  * Binance USDT-M REST (ccxt.binanceusdm)  canlı tarama ve arşivde olmayan son günler için

Tüm DataFrame'ler aynı biçimdedir:
  index  : mumun AÇILIŞ zamanı (UTC, tz-aware DatetimeIndex), artan, tekrar yok
  sütunlar: open, high, low, close, volume, quote_volume (float)
Kapanmamış mum hiçbir zaman döndürülmez (`kapanmamislari_at`).
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

ARSIV = "https://data.binance.vision"
ARSIV_LISTE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
SUTUNLAR = ["open", "high", "low", "close", "volume", "quote_volume"]
ARALIK_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
             "3d": 259_200_000, "1w": 604_800_000}
VARSAYILAN_ONBELLEK = Path(__file__).resolve().parent.parent / "veri_onbellek"

_SEMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")


def sembol_dogrula(sembol: str) -> str:
    """'BTC/USDT:USDT', 'btcusdt' gibi girdileri 'BTCUSDT' biçimine çevirir; geçersizse ValueError."""
    s = sembol.upper().replace("/USDT:USDT", "USDT").replace("/", "").replace(":USDT", "").strip()
    if not _SEMBOL_RE.match(s):
        raise ValueError(f"Geçersiz sembol: {sembol!r}")
    return s


def bos_df() -> pd.DataFrame:
    return pd.DataFrame(columns=SUTUNLAR, index=pd.DatetimeIndex([], tz="UTC", name="zaman"), dtype=float)


def satirlardan_df(satirlar: Iterable[list]) -> pd.DataFrame:
    """[[open_ms, o, h, l, c, v, (qv)], ...] -> standart DataFrame."""
    satirlar = list(satirlar)
    if not satirlar:
        return bos_df()
    a = np.array([[float(x) for x in r[:7]] if len(r) >= 7 else [float(x) for x in r[:6]] + [np.nan] for r in satirlar])
    df = pd.DataFrame(a[:, 1:], columns=SUTUNLAR, index=pd.to_datetime(a[:, 0].astype("int64"), unit="ms", utc=True))
    df.index.name = "zaman"
    return temizle(df)


def temizle(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def kapanmamislari_at(df: pd.DataFrame, aralik: str = "1h", simdi_ms: int | None = None) -> pd.DataFrame:
    """Açılış + aralık > şimdi olan (henüz kapanmamış) mumları atar."""
    if df.empty:
        return df
    simdi_ms = simdi_ms if simdi_ms is not None else int(time.time() * 1000)
    kapanis_ms = df.index.as_unit("ms").asi8 + ARALIK_MS[aralik]
    return df[kapanis_ms <= simdi_ms]


def yeniden_ornekle(df: pd.DataFrame, aralik: str) -> pd.DataFrame:
    """1s mumdan daha büyük aralığa (ör. 4h) çevirir. Etiket = dilimin açılışı (Binance ile aynı).
    Son dilim eksikse (içindeki saatlerin hepsi gelmemişse) atılır; kısmi mum asla kullanılmaz."""
    if df.empty:
        return df.copy()
    # Binance hizası (arşivden doğrulandı): gün = UTC gece yarısı; hafta = Pazartesi 00:00 UTC;
    # 3 gün = 1970-01-02'den itibaren 72 saatlik dilimler (ör. 2026-10-23, 26, 29)
    if aralik == "1w":
        kural, koken = "168h", pd.Timestamp("1970-01-05", tz="UTC")
    elif aralik == "3d":
        kural, koken = "72h", pd.Timestamp("1970-01-02", tz="UTC")
    else:
        kural, koken = (f"{int(aralik[:-1]) * 24}h" if aralik.endswith("d") else aralik), "epoch"
    g = df.resample(kural, label="left", closed="left", origin=koken)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "quote_volume": g["quote_volume"].sum(),
    }).dropna(subset=["close"])
    # Son dilim: bitiş zamanı, kaynaktaki son mumun kapanışından sonraysa eksiktir.
    kaynak_ms = ARALIK_MS.get(_aralik_tahmin(df), 3_600_000)
    son_kapanis = df.index[-1] + pd.Timedelta(milliseconds=kaynak_ms)
    hedef = pd.Timedelta(milliseconds=ARALIK_MS[aralik])
    if len(out) and out.index[-1] + hedef > son_kapanis:
        out = out.iloc[:-1]
    return out


def _aralik_tahmin(df: pd.DataFrame) -> str:
    if len(df) < 2:
        return "1h"
    ms = int(pd.Series(df.index).diff().dropna().median().total_seconds() * 1000)
    for k, v in ARALIK_MS.items():
        if v == ms:
            return k
    return "1h"


# ---------------------------------------------------------------- arşiv (data.binance.vision)
_oturum = requests.Session()
_oturum.headers["User-Agent"] = "vadeli-tarayici/1.0"


def _zip_indir(url: str, deneme: int = 4) -> bytes | None:
    bekle = 1.0
    for i in range(deneme):
        try:
            r = _oturum.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:  # ağ hatası: geri çekil
            log.warning("indirme hatası (%s/%s) %s: %s", i + 1, deneme, url, e)
            time.sleep(bekle)
            bekle *= 2
    return None


def _zipten_csv(icerik: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(icerik)) as z:
        ad = z.namelist()[0]
        ham = z.read(ad)
    ilk = ham[:20].decode(errors="ignore")
    basliksiz = ilk[:1].isdigit()
    return pd.read_csv(io.BytesIO(ham), header=None if basliksiz else 0)


def _kline_zip_df(icerik: bytes) -> pd.DataFrame:
    t = _zipten_csv(icerik)
    t = t.iloc[:, [0, 1, 2, 3, 4, 5, 7]]
    t.columns = ["t", *SUTUNLAR]
    t["t"] = t["t"].astype("int64")
    t.loc[t["t"] > 10**14, "t"] //= 1000  # 2025 sonrası bazı arşivler mikro saniye
    df = t.set_index(pd.to_datetime(t["t"], unit="ms", utc=True)).drop(columns="t")
    df.index.name = "zaman"
    return temizle(df)


def _csv_oku(yol: Path) -> pd.DataFrame:
    t = pd.read_csv(yol, index_col=0)
    t.index = pd.to_datetime(t.index, utc=True, format="ISO8601")
    t.index.name = "zaman"
    return t


def _ay_kumesi(index: pd.DatetimeIndex) -> set[str]:
    return set(index.strftime("%Y-%m")) if len(index) else set()


def _bos_aylar(yol: Path) -> set[str]:
    """Arşivde bulunmayan (404) aylar; tekrar tekrar sorulmasın diye kaydedilir."""
    y = yol.with_suffix(".bos")
    return set(y.read_text().split()) if y.exists() else set()


def _bos_aylar_yaz(yol: Path, aylar: set[str]) -> None:
    yol.with_suffix(".bos").write_text("\n".join(sorted(aylar)))


def _aylar(baslangic: str, bitis: pd.Timestamp) -> list[str]:
    b = pd.Timestamp(bitis).tz_localize(None) if pd.Timestamp(bitis).tzinfo else pd.Timestamp(bitis)
    return [p.strftime("%Y-%m") for p in pd.period_range(baslangic, b, freq="M")]


def arsivden_mumlar(sembol: str, aralik: str = "1h", baslangic: str = "2020-01",
                    bitis: str | None = None, gunluk_tamamla: bool = False,
                    onbellek: Path = VARSAYILAN_ONBELLEK) -> pd.DataFrame:
    """Arşivden aylık ZIP'leri indirip CSV olarak önbelleğe alır. Önbellekte olan aylar tekrar indirilmez.
    `bitis` (YYYY-MM) verilmezse son tamamlanmış ay kullanılır."""
    sembol = sembol_dogrula(sembol)
    onbellek.mkdir(parents=True, exist_ok=True)
    yol = onbellek / f"{sembol}_{aralik}.csv"
    eski = _csv_oku(yol) if yol.exists() else bos_df()
    simdi = pd.Timestamp.now(tz="UTC")
    son_ay = pd.Period(bitis, "M") if bitis else (simdi.to_period("M") - 1)
    parcalar = [eski]
    var_olan = _ay_kumesi(eski.index) | _bos_aylar(yol)
    if len(eski):  # son ay günlük ZIP'lerle kısmen doldurulmuş olabilir: tamamlanmamışsa yeniden indir
        son = eski.index[-1]
        if son + pd.Timedelta(milliseconds=ARALIK_MS[aralik]) < (son.tz_localize(None).to_period("M") + 1).to_timestamp().tz_localize("UTC"):
            var_olan.discard(son.strftime("%Y-%m"))
    eksik = [a for a in _aylar(baslangic, son_ay.to_timestamp()) if a not in var_olan]
    bos = _bos_aylar(yol)
    # Sembolün işlem görmeye başladığından önceki aylar 404 döner: sorun değil, kaydedilir.
    for ay in eksik:
        url = f"{ARSIV}/data/futures/um/monthly/klines/{sembol}/{aralik}/{sembol}-{aralik}-{ay}.zip"
        icerik = _zip_indir(url)
        if icerik:
            parcalar.append(_kline_zip_df(icerik))
        elif ay < simdi.strftime("%Y-%m"):
            bos.add(ay)
    _bos_aylar_yaz(yol, bos)
    if gunluk_tamamla:
        gun = (son_ay + 1).to_timestamp().tz_localize("UTC")
        while gun < simdi.normalize():
            g = gun.strftime("%Y-%m-%d")
            icerik = _zip_indir(f"{ARSIV}/data/futures/um/daily/klines/{sembol}/{aralik}/{sembol}-{aralik}-{g}.zip")
            if icerik:
                parcalar.append(_kline_zip_df(icerik))
            gun += pd.Timedelta(days=1)
    df = temizle(pd.concat([p for p in parcalar if not p.empty])) if any(not p.empty for p in parcalar) else bos_df()
    df = kapanmamislari_at(df, aralik)
    if len(df) != len(eski):
        df.to_csv(yol)
    return df


def arsivden_fonlama(sembol: str, baslangic: str = "2020-01", bitis: str | None = None,
                     onbellek: Path = VARSAYILAN_ONBELLEK) -> pd.Series:
    """Gerçekleşmiş fonlama oranları (index: fonlama zamanı UTC, değer: oran, ör. 0.0001 = %0.01)."""
    sembol = sembol_dogrula(sembol)
    onbellek.mkdir(parents=True, exist_ok=True)
    yol = onbellek / f"{sembol}_fonlama.csv"
    s = _csv_oku(yol).iloc[:, 0] if yol.exists() else pd.Series(dtype=float)
    simdi = pd.Timestamp.now(tz="UTC")
    son_ay = pd.Period(bitis, "M") if bitis else (simdi.to_period("M") - 1)
    bos = _bos_aylar(yol)
    var_olan = _ay_kumesi(s.index) | bos
    parcalar = [s]
    for ay in _aylar(baslangic, son_ay.to_timestamp()):
        if ay in var_olan:
            continue
        icerik = _zip_indir(f"{ARSIV}/data/futures/um/monthly/fundingRate/{sembol}/{sembol}-fundingRate-{ay}.zip")
        if not icerik:
            bos.add(ay)
            continue
        t = _zipten_csv(icerik)
        p = pd.Series(t.iloc[:, 2].astype(float).values,
                      index=pd.to_datetime(t.iloc[:, 0].astype("int64"), unit="ms", utc=True))
        parcalar.append(p)
    s2 = pd.concat([p for p in parcalar if len(p)]) if any(len(p) for p in parcalar) else pd.Series(dtype=float)
    if len(s2):
        s2 = s2[~s2.index.duplicated(keep="last")].sort_index()
        s2.name = "oran"
        s2.index.name = "zaman"
        if len(s2) != len(s):
            s2.to_frame().to_csv(yol)
    _bos_aylar_yaz(yol, bos)
    return s2


def arsiv_sembolleri() -> list[str]:
    """Arşivde aylık 1s verisi olan tüm USDT-M sembolleri (S3 listesi)."""
    semboller: list[str] = []
    isaret = ""
    while True:
        r = _oturum.get(ARSIV_LISTE, params={"prefix": "data/futures/um/monthly/klines/", "delimiter": "/",
                                             "marker": isaret}, timeout=60)
        r.raise_for_status()
        bulunan = re.findall(r"<Prefix>data/futures/um/monthly/klines/([A-Z0-9]+)/</Prefix>", r.text)
        semboller += bulunan
        m = re.search(r"<NextMarker>(.*?)</NextMarker>", r.text)
        if not m:
            break
        isaret = m.group(1)
    return sorted({s for s in semboller if s.endswith("USDT")})


def arsivden_hacim_sirasi(ay: str, n: int = 50, aday: list[str] | None = None) -> list[tuple[str, float]]:
    """Belirtilen ayın günlük mumlarından USDT hacmine göre ilk n sembol (arşiv tabanlı evren seçimi)."""
    aday = aday or arsiv_sembolleri()

    def hacim(s: str) -> tuple[str, float]:
        icerik = _zip_indir(f"{ARSIV}/data/futures/um/monthly/klines/{s}/1d/{s}-1d-{ay}.zip", deneme=2)
        if not icerik:
            return s, 0.0
        df = _kline_zip_df(icerik)
        tam = len(df) >= 25  # ay boyunca işlem görmüş olsun
        return s, float(df["quote_volume"].sum()) if tam else 0.0

    with ThreadPoolExecutor(16) as ex:
        sonuc = list(ex.map(hacim, aday))
    sonuc = [x for x in sonuc if x[1] > 0 and not x[0].startswith(("USDC", "BUSD", "TUSD", "FDUSD"))]
    sonuc.sort(key=lambda x: -x[1])
    return sonuc[:n]


# ---------------------------------------------------------------- canlı REST (ccxt.binanceusdm)
class BinanceREST:
    """ccxt.binanceusdm üzerinden herkese açık uç noktalar. Anahtar verilmez; emir fonksiyonu yoktur.
    Her çağrı üstel geri çekilme (exponential backoff) ile yeniden denenir."""

    def __init__(self, deneme: int = 5):
        import ccxt  # isteğe bağlı bağımlılık; sadece canlıda gerekir

        self.ccxt = ccxt
        self.borsa = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
        self.deneme = deneme

    def _cagir(self, fn, *a, **k):
        bekle = 1.0
        for i in range(self.deneme):
            try:
                return fn(*a, **k)
            except (self.ccxt.RateLimitExceeded, self.ccxt.DDoSProtection) as e:
                log.warning("Hız limiti, %.0f sn bekleniyor: %s", bekle * 4, e)
                time.sleep(bekle * 4)
            except (self.ccxt.NetworkError, self.ccxt.ExchangeNotAvailable, self.ccxt.RequestTimeout) as e:
                log.warning("Ağ hatası (%d/%d): %s", i + 1, self.deneme, e)
                time.sleep(bekle)
            bekle = min(bekle * 2, 60)
        return fn(*a, **k)

    def evren(self, n: int = 50) -> list[dict]:
        """Hacme göre ilk n USDT-M perpetual (aktif, USDT teminatlı)."""
        piyasalar = self._cagir(self.borsa.load_markets, True)
        perp = {m["id"]: m for m in piyasalar.values()
                if m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("active")
                and m.get("settle") == "USDT"}
        ham = self._cagir(self.borsa.fapiPublicGetTicker24hr)
        liste = [{"sembol": t["symbol"], "hacim24": float(t["quoteVolume"]), "fiyat": float(t["lastPrice"])}
                 for t in ham if t["symbol"] in perp]
        liste.sort(key=lambda x: -x["hacim24"])
        return liste[:n]

    def mumlar(self, sembol: str, aralik: str = "1h", baslangic_ms: int | None = None, limit: int = 1500,
               toplam: int | None = None) -> pd.DataFrame:
        """Kapanmış mumlar. `toplam` verilirse geriye doğru o kadar mum toplanır."""
        sembol = sembol_dogrula(sembol)
        satirlar: list[list] = []
        if toplam:
            bitis = int(time.time() * 1000)
            baslangic_ms = bitis - toplam * ARALIK_MS[aralik]
        while True:
            params = {"symbol": sembol, "interval": aralik, "limit": limit}
            if baslangic_ms is not None:
                params["startTime"] = baslangic_ms
            ham = self._cagir(self.borsa.fapiPublicGetKlines, params)
            if not ham:
                break
            satirlar += [[int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7]] for r in ham]
            if len(ham) < limit or baslangic_ms is None:
                break
            baslangic_ms = int(ham[-1][0]) + ARALIK_MS[aralik]
        return kapanmamislari_at(satirlardan_df(satirlar), aralik)

    def fonlama(self, sembol: str, baslangic_ms: int | None = None) -> pd.Series:
        """fetch_funding_rate_history ile gerçek fonlama oranları."""
        s = sembol_dogrula(sembol)
        ccxt_sembol = s[:-4] + "/USDT:USDT"
        kayitlar: list[dict] = []
        while True:
            parca = self._cagir(self.borsa.fetch_funding_rate_history, ccxt_sembol, baslangic_ms, 1000)
            if not parca:
                break
            kayitlar += parca
            if len(parca) < 1000:
                break
            baslangic_ms = parca[-1]["timestamp"] + 1
        if not kayitlar:
            return pd.Series(dtype=float)
        return pd.Series([k["fundingRate"] for k in kayitlar],
                         index=pd.to_datetime([k["timestamp"] for k in kayitlar], unit="ms", utc=True)).sort_index()


def gecmis_yukle(sembol: str, baslangic: str = "2020-01", bitis: str | None = None,
                 onbellek: Path = VARSAYILAN_ONBELLEK) -> tuple[pd.DataFrame, pd.Series]:
    """Backtest için 1s mum + gerçek fonlama (önbellekli). `bitis` (YYYY-MM) verilirse o ayın sonunda kesilir:
    önbellekte ileri test için indirilmiş daha yeni günler olsa bile backtest'e sızmaz."""
    df = arsivden_mumlar(sembol, "1h", baslangic, bitis, onbellek=onbellek)
    f = arsivden_fonlama(sembol, baslangic, bitis, onbellek=onbellek)
    if bitis:
        son = (pd.Period(bitis, "M") + 1).to_timestamp().tz_localize("UTC")
        df = df[df.index < son]
        f = f[f.index < son] if len(f) else f
    return df, f


# ---------------------------------------------------------------- sentetik veri
def rastgele_yuruyus(n: int = 20_000, tohum: int = 0, baslangic_fiyat: float = 100.0, saatlik_vol: float = 0.008,
                     surukleme: float = 0.0, baslangic: str = "2021-01-01", alt_adim: int = 60) -> pd.DataFrame:
    """Sürüklenmesiz (veya verilen sürüklenmeli) geometrik rastgele yürüyüş, gerçekçi OHLC.
    Kenarı (edge) olmayan veri: doğru bir sistem burada maliyetlerden sonra kâr ETMEMELİ."""
    rng = np.random.default_rng(tohum)
    # Mum içi `alt_adim` adım (dakika benzeri). Az adım kullanmak stopların "tam stop fiyatından" dolmasını
    # gerçek yoldan daha iyi gösterir (atlama payı yok sayılır) ve sahte bir kenar üretir; 60 adımda bu etki ihmal edilir.
    k = alt_adim
    alt = rng.normal(surukleme / k, saatlik_vol / np.sqrt(k), size=(n, k)).astype(np.float64)
    yol = baslangic_fiyat * np.exp(np.cumsum(alt.ravel())).reshape(n, k)
    acilis = np.concatenate([[baslangic_fiyat], yol[:-1, -1]])
    kapanis = yol[:, -1]
    yuksek = np.maximum(np.maximum(acilis, yol.max(axis=1)), kapanis)
    dusuk = np.minimum(np.minimum(acilis, yol.min(axis=1)), kapanis)
    hacim = rng.lognormal(10, 0.5, n)
    idx = pd.date_range(baslangic, periods=n, freq="1h", tz="UTC", name="zaman")
    return pd.DataFrame({"open": acilis, "high": yuksek, "low": dusuk, "close": kapanis,
                         "volume": hacim, "quote_volume": hacim * kapanis}, index=idx)


def getiri_karistir(df: pd.DataFrame, tohum: int = 0) -> pd.DataFrame:
    """Gerçek verinin saatlik getirilerini karıştırır: dağılım aynı, zaman yapısı (trend) yok."""
    rng = np.random.default_rng(tohum)
    c = df["close"].values
    o = df["open"].values
    lr = np.diff(np.log(c))
    perm = rng.permutation(len(lr))
    yeni_c = c[0] * np.exp(np.concatenate([[0.0], np.cumsum(lr[perm])]))
    # high/low/open'ı aynı mumun göreli oranlarıyla taşı
    oran_h = (df["high"].values / c)[1:][perm]
    oran_l = (df["low"].values / c)[1:][perm]
    oran_o = (o / c)[1:][perm]
    out = df.copy()
    out["close"] = yeni_c
    out.iloc[1:, out.columns.get_loc("open")] = yeni_c[1:] * oran_o
    out.iloc[1:, out.columns.get_loc("high")] = np.maximum(yeni_c[1:] * oran_h, np.maximum(yeni_c[1:], yeni_c[1:] * oran_o))
    out.iloc[1:, out.columns.get_loc("low")] = np.minimum(yeni_c[1:] * oran_l, np.minimum(yeni_c[1:], yeni_c[1:] * oran_o))
    return out


def simdi_utc() -> datetime:
    return datetime.now(timezone.utc)
