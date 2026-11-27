"""Türev piyasası konumlanma verileri (CoinGlass'ın Binance için gösterdiği ham verinin aynısı, doğrudan Binance'ten):

  * Açık pozisyon (open interest, USDT)
  * En büyük trader'ların long/short POZİSYON oranı (top_ls) ve HESAP oranı (top_hesap_ls)
  * Tüm hesapların long/short oranı (ls_hesap)
  * Taker alım/satım hacmi oranı (taker_oran > 1: agresif alıcı baskın)

Kaynaklar (anahtarsız, herkese açık):
  * Geçmiş: data.binance.vision  data/futures/um/daily/metrics/<SEMBOL>/  (5 dk, 2021-12'den beri)
  * Canlı:  fapi.binance.com/futures/data/{openInterestHist, topLongShortPositionRatio, ...}  (son 30 gün)

Zaman kuralı: 1s mum T (T..T+1s) için yalnızca create_time ∈ [T, T+1s) anlık görüntüleri kullanılır; son görüntü
T+55dk'dır. Yani mum kapanışından en az 5 dk önce bilinen veri: look-ahead yok, canlıda yayın gecikmesine pay var.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import veri

log = logging.getLogger(__name__)
METRIK_BASLANGIC = "2021-12-01"
SUTUN_ESLE = {
    "sum_open_interest_value": "oi",
    "sum_toptrader_long_short_ratio": "top_ls",
    "count_toptrader_long_short_ratio": "top_hesap_ls",
    "count_long_short_ratio": "ls_hesap",
    "sum_taker_long_short_vol_ratio": "taker_oran",
}
METRIK_SUTUN = list(SUTUN_ESLE.values())


def _gunluk_oku(icerik: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(icerik)) as z:
        t = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    t = t.rename(columns=SUTUN_ESLE)
    t.index = pd.to_datetime(t["create_time"], utc=True)
    return t[[c for c in METRIK_SUTUN if c in t.columns]].apply(pd.to_numeric, errors="coerce")


def saatlige(t: pd.DataFrame) -> pd.DataFrame:
    """5 dk anlık görüntüler → 1s mum etiketi (açılış). Seviyeler: son değer; taker oranı: ortalama."""
    if t.empty:
        return t
    g = t.resample("1h", label="left", closed="left", origin="epoch")
    out = g[["oi", "top_ls", "top_hesap_ls", "ls_hesap"]].last()
    out["taker_oran"] = g["taker_oran"].mean()
    out.index.name = "zaman"
    return out.dropna(how="all")


def arsivden_metrik(sembol: str, bitis: str = "2026-10-31", onbellek: Path = veri.VARSAYILAN_ONBELLEK,
                    is_parcacigi: int = 24) -> pd.DataFrame:
    """Günlük metrik ZIP'lerini indirip 1s'e çevirir, önbelleğe alır. Önbellekte olan günler tekrar indirilmez."""
    sembol = veri.sembol_dogrula(sembol)
    onbellek.mkdir(parents=True, exist_ok=True)
    yol = onbellek / f"{sembol}_metrik_1h.csv"
    gunler_yol = yol.with_suffix(".gunler")
    eski = veri._csv_oku(yol) if yol.exists() else pd.DataFrame(columns=METRIK_SUTUN)
    bitti = set(gunler_yol.read_text().split()) if gunler_yol.exists() else set()
    tum = [d.strftime("%Y-%m-%d") for d in pd.date_range(METRIK_BASLANGIC, bitis, freq="D")]
    eksik = [g for g in tum if g not in bitti]
    if not eksik:
        return eski

    def indir(g: str):
        icerik = veri._zip_indir(f"{veri.ARSIV}/data/futures/um/daily/metrics/{sembol}/{sembol}-metrics-{g}.zip", deneme=3)
        return g, (_gunluk_oku(icerik) if icerik else None)

    parcalar = [eski] if len(eski) else []
    with ThreadPoolExecutor(is_parcacigi) as ex:
        for g, t in ex.map(indir, eksik):
            bitti.add(g)  # 404 (sembol o gün yoktu) da "bitti" sayılır
            if t is not None and len(t):
                parcalar.append(saatlige(t))
    if parcalar:
        df = pd.concat(parcalar)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.index.name = "zaman"
        df.to_csv(yol)
    else:
        df = pd.DataFrame(columns=METRIK_SUTUN)
    gunler_yol.write_text("\n".join(sorted(bitti)))
    return df


# ------------------------------------------------------------------ canlı (REST, anahtarsız)
class BinanceMetrikREST:
    """fapi.binance.com/futures/data uç noktaları; son 30 günle sınırlıdır. 5 dk → saatlik (arşivle aynı dönüşüm)."""

    def __init__(self, rest: "veri.BinanceREST"):
        self.rest = rest

    def metrik(self, sembol: str, alanlar: tuple[str, ...] = tuple(METRIK_SUTUN)) -> pd.DataFrame:
        b = self.rest.borsa
        s = veri.sembol_dogrula(sembol)
        limit = 500
        parcalar = {}
        uclar = {
            "oi": (b.fapiDataGetOpenInterestHist, "sumOpenInterestValue"),
            "top_ls": (b.fapiDataGetTopLongShortPositionRatio, "longShortRatio"),
            "top_hesap_ls": (b.fapiDataGetTopLongShortAccountRatio, "longShortRatio"),
            "ls_hesap": (b.fapiDataGetGlobalLongShortAccountRatio, "longShortRatio"),
            "taker_oran": (b.fapiDataGetTakerlongshortRatio, "buySellRatio"),
        }
        for ad, (fn, alan) in uclar.items():
            if ad not in alanlar:
                continue
            try:
                ham = self.rest._cagir(fn, {"symbol": s, "period": "5m", "limit": limit})
                parcalar[ad] = pd.Series([float(x[alan]) for x in ham],
                                         index=pd.to_datetime([int(x["timestamp"]) for x in ham], unit="ms", utc=True))
            except Exception as e:  # tek uç hatası diğerlerini durdurmaz
                log.warning("%s %s metriği alınamadı: %s", s, ad, e)
        if not parcalar:
            return pd.DataFrame(columns=METRIK_SUTUN)
        t = pd.DataFrame(parcalar)
        for c in METRIK_SUTUN:
            if c not in t:
                t[c] = np.nan
        # Kapanmamış saatin anlık görüntüleri: o saat mumu henüz kapanmadı → at
        simdi = pd.Timestamp.now(tz="UTC").floor("h")
        return saatlige(t[t.index < simdi])


# ------------------------------------------------------------------ özellikler (look-ahead yok)
def ozellikler(metrik_1h: pd.DataFrame, fonlama: pd.Series | None, index: pd.DatetimeIndex, tf: str,
               oi_n: int = 6, z_n: int = 180) -> pd.DataFrame:
    """Tetik zaman dilimi mumlarına hizalanmış özellikler. Satır T (açılış), T+tf kapanışında bilinen veriyi taşır.

      oi_deg   : açık pozisyonun son `oi_n` mumdaki yüzde değişimi
      ls_z     : tüm hesaplar long/short oranının `z_n` mumluk z-skoru (kalabalık ölçüsü)
      top_ls   : büyük trader'ların long/short pozisyon oranı
      taker    : mum içindeki ortalama taker alım/satım oranı
      fonlama  : kapanışa kadar gerçekleşmiş son fonlama oranı
    """
    out = pd.DataFrame(index=index)
    if metrik_1h is not None and len(metrik_1h):
        m = metrik_1h.sort_index().reindex(columns=METRIK_SUTUN)  # eksik sütunlar (ör. yalnız OI) NaN
        if tf != "1h":
            g = m.resample(tf, label="left", closed="left", origin="epoch")
            m = g[["oi", "top_ls", "top_hesap_ls", "ls_hesap"]].last()
            m["taker_oran"] = g["taker_oran"].mean()
        m = m.reindex(index)
        oi = m["oi"].where(m["oi"] > 0)  # arşivde ara sıra 0 yazılmış saatler: veri yok say
        out["oi"] = oi
        out["oi_deg"] = oi / oi.shift(oi_n) - 1
        ls = m["ls_hesap"]
        out["ls_hesap"] = ls
        out["ls_z"] = (ls - ls.rolling(z_n, min_periods=z_n // 2).mean()) / ls.rolling(z_n, min_periods=z_n // 2).std()
        out["top_ls"] = m["top_ls"]
        out["taker"] = m["taker_oran"]
    else:
        for c in ("oi", "oi_deg", "ls_hesap", "ls_z", "top_ls", "taker"):
            out[c] = np.nan
    if fonlama is not None and len(fonlama):
        f = fonlama.copy()
        f.index = f.index.floor("min")
        f = f[~f.index.duplicated(keep="last")].sort_index()
        L = pd.Timedelta(milliseconds=veri.ARALIK_MS[tf])
        kapanis = index + L
        out["fonlama"] = f.reindex(f.index.union(kapanis)).ffill().reindex(kapanis).to_numpy()
    else:
        out["fonlama"] = np.nan
    return out
