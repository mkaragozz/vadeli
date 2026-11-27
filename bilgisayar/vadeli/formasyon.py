"""Formasyon, destek/direnç ve indikatör sinyalleri + "hedef stoptan önce mi?" istatistiği (DENEYLER.md §4, ön kayıtlı).

Tüm sinyaller satır i'nin KAPANIŞINDA bilinen veriyle hesaplanır; işlem i+1 açılışında. Pivot (tepe/dip) i'de oluşur ama
ancak i+K kapanışında bilinir (sağında K mum gerekir) → yalnız i+K'den sonra kullanılır.

Bu modül hem araştırmada (uret) hem canlı tespitte (tespit: son mumdaki sinyaller) kullanılır.
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import veri
from .strateji import atr as atr_hesap
from .strateji import ema

log = logging.getLogger(__name__)
KOK = Path(__file__).resolve().parent.parent
K_PIVOT = 5
STOP_ATR = 1.5
UFUK = 50
MALIYET = 0.001 + 0.0005  # spot: komisyon + kayma, yön başına
HOLDOUT = pd.Timestamp("2025-01-01", tz="UTC")
BASLANGIC = pd.Timestamp("2021-01-01", tz="UTC")
HEDEFLER = (1.0, 2.0, "seviye")
HEDEF_AD = {1.0: "1:1", 2.0: "1:2", "seviye": "seviye"}

AD = {  # sinyal adı → (Türkçe ad, aile)
    "yutan": ("Yutan (engulfing)", "mum"), "cekic": ("Çekiç / Asılı adam", "mum"), "ters_cekic": ("Ters çekiç / Kayan yıldız", "mum"),
    "doji": ("Yusufçuk / Mezar taşı doji", "mum"), "yildiz": ("Sabah / Akşam yıldızı", "mum"),
    "uc_asker": ("Üç beyaz asker / Üç kara karga", "mum"), "delen": ("Delen çizgi / Kara bulut", "mum"),
    "harami": ("Harami", "mum"), "marubozu": ("Marubozu", "mum"),
    "ikili": ("İkili dip / İkili tepe", "grafik"), "obo": ("Ters OBO / OBO", "grafik"), "ucgen": ("Üçgen kırılımı", "grafik"),
    "bayrak": ("Bayrak", "grafik"),
    "dd_kirilim": ("Destek/direnç kırılımı", "dd"), "dd_kirilim_hacim": ("Destek/direnç kırılımı + hacim", "dd"),
    "rsi": ("RSI 30/70 dönüşü", "indikator"), "macd": ("MACD kesişimi", "indikator"), "ema_kesisim": ("EMA20/50 kesişimi", "indikator"),
    "bollinger": ("Bollinger dönüşü", "indikator"), "donchian": ("Donchian 20 kırılımı", "indikator"),
}


# ------------------------------------------------------------------ göstergeler
def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def pivotlar(h: np.ndarray, l: np.ndarray, k: int = K_PIVOT) -> tuple[np.ndarray, np.ndarray]:
    """Pivot tepe/dip (i'de, i±k aralığının en yükseği/düşüğü). Bilinme anı i+k."""
    n = len(h)
    pt = np.zeros(n, bool)
    pd_ = np.zeros(n, bool)
    if n < 2 * k + 1:
        return pt, pd_
    from numpy.lib.stride_tricks import sliding_window_view as sw
    hm = sw(h, 2 * k + 1).max(axis=1)
    lm = sw(l, 2 * k + 1).min(axis=1)
    pt[k:n - k] = h[k:n - k] >= hm
    pd_[k:n - k] = l[k:n - k] <= lm
    return pt, pd_


# ------------------------------------------------------------------ sinyaller
def sinyaller(df: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{ad: (long_maske, short_maske)} — satır i'nin kapanışında bilinen."""
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "quote_volume"))
    cs = df["close"]
    n = len(df)
    a = atr_hesap(df, 14).to_numpy()
    govde = np.abs(c - o)
    aralik = np.maximum(h - l, 1e-12)
    ust_fitil = h - np.maximum(o, c)
    alt_fitil = np.minimum(o, c) - l
    yesil, kirmizi = c > o, c < o
    sma10 = cs.rolling(10).mean().to_numpy()
    dusus = c < sma10   # dönüş formasyonu bağlamı: önceki eğilim aşağı
    yukselis = c > sma10
    sh = lambda x, k=1: np.concatenate([np.full(k, np.nan if x.dtype.kind == "f" else False), x[:-k]])
    o1, c1, h1, l1, o2, c2 = sh(o), sh(c), sh(h), sh(l), sh(o, 2), sh(c, 2)
    g1 = np.abs(c1 - o1)
    d1 = sh(dusus).astype(bool)
    y1 = sh(yukselis).astype(bool)
    S: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    # --- mum formasyonları
    S["yutan"] = (d1 & (c1 < o1) & yesil & (o <= c1) & (c >= o1) & (govde > g1),
                  y1 & (c1 > o1) & kirmizi & (o >= c1) & (c <= o1) & (govde > g1))
    kucuk_govde = govde <= 0.35 * aralik
    S["cekic"] = (d1 & kucuk_govde & (alt_fitil >= 2 * govde) & (ust_fitil <= 0.25 * aralik),
                  y1 & kucuk_govde & (alt_fitil >= 2 * govde) & (ust_fitil <= 0.25 * aralik))   # asılı adam
    S["ters_cekic"] = (d1 & kucuk_govde & (ust_fitil >= 2 * govde) & (alt_fitil <= 0.25 * aralik),
                       y1 & kucuk_govde & (ust_fitil >= 2 * govde) & (alt_fitil <= 0.25 * aralik))  # kayan yıldız
    doji = govde <= 0.1 * aralik
    S["doji"] = (d1 & doji & (alt_fitil >= 0.6 * aralik), y1 & doji & (ust_fitil >= 0.6 * aralik))
    g2 = np.abs(c2 - o2)
    orta_kucuk = g1 <= 0.3 * np.maximum(g2, 1e-12)
    d2 = sh(dusus, 2).astype(bool)
    y2 = sh(yukselis, 2).astype(bool)
    S["yildiz"] = (d2 & (c2 < o2) & orta_kucuk & yesil & (c > (o2 + c2) / 2),
                   y2 & (c2 > o2) & orta_kucuk & kirmizi & (c < (o2 + c2) / 2))
    yes1, yes2 = sh(yesil).astype(bool), sh(yesil, 2).astype(bool)
    kir1, kir2 = sh(kirmizi).astype(bool), sh(kirmizi, 2).astype(bool)
    buyuk = govde >= 0.5 * aralik
    b1, b2 = sh(buyuk).astype(bool), sh(buyuk, 2).astype(bool)
    S["uc_asker"] = (yesil & yes1 & yes2 & buyuk & b1 & b2 & (c > c1) & (c1 > c2),
                     kirmizi & kir1 & kir2 & buyuk & b1 & b2 & (c < c1) & (c1 < c2))
    # Kripto 7/24: açılış ≈ önceki kapanış (boşluk yok). Borsa tanımlarındaki boşluk şartı "eşit veya" olarak uyarlandı.
    S["delen"] = (d1 & (c1 < o1) & (g1 >= 0.5 * sh(aralik)) & yesil & (o <= c1) & (c > (o1 + c1) / 2) & (c < o1),
                  y1 & (c1 > o1) & (g1 >= 0.5 * sh(aralik)) & kirmizi & (o >= c1) & (c < (o1 + c1) / 2) & (c > o1))
    ic = (np.minimum(o, c) >= np.minimum(o1, c1)) & (np.maximum(o, c) <= np.maximum(o1, c1)) & (govde < 0.5 * g1)
    S["harami"] = (d1 & (c1 < o1) & yesil & ic, y1 & (c1 > o1) & kirmizi & ic)
    S["marubozu"] = (yesil & (govde >= 0.95 * aralik) & (aralik >= a), kirmizi & (govde >= 0.95 * aralik) & (aralik >= a))
    # --- indikatörler
    r = rsi(cs).to_numpy()
    r1 = sh(r)
    S["rsi"] = ((r1 < 30) & (r >= 30), (r1 > 70) & (r <= 70))
    m = ema(cs, 12) - ema(cs, 26)
    sig = m.ewm(span=9, adjust=False, min_periods=9).mean()
    fark = (m - sig).to_numpy()
    f1 = sh(fark)
    S["macd"] = ((f1 < 0) & (fark >= 0), (f1 > 0) & (fark <= 0))
    e20, e50 = ema(cs, 20).to_numpy(), ema(cs, 50).to_numpy()
    k1 = sh(e20 - e50)
    S["ema_kesisim"] = ((k1 < 0) & (e20 - e50 >= 0), (k1 > 0) & (e20 - e50 <= 0))
    ort = cs.rolling(20).mean()
    sd = cs.rolling(20).std()
    alt_b, ust_b = (ort - 2 * sd).to_numpy(), (ort + 2 * sd).to_numpy()
    S["bollinger"] = ((c1 < sh(alt_b)) & (c > alt_b), (c1 > sh(ust_b)) & (c < ust_b))
    du = df["high"].rolling(20).max().shift(1).to_numpy()
    da = df["low"].rolling(20).min().shift(1).to_numpy()
    S["donchian"] = ((c > du) & ~(c1 > sh(du)), (c < da) & ~(c1 < sh(da)))
    # --- destek/direnç ve grafik formasyonları (pivotlar, gecikmeli)
    dd = _dd_ve_grafik(o, h, l, c, v, a)
    S.update(dd)
    for k, (x, y) in S.items():
        S[k] = (np.nan_to_num(x, nan=0).astype(bool), np.nan_to_num(y, nan=0).astype(bool))
    return S


def _dd_ve_grafik(o, h, l, c, v, a) -> dict:
    n = len(c)
    pt, pdp = pivotlar(h, l)
    K = K_PIVOT
    hacim_ort = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    out = {k: (np.zeros(n, bool), np.zeros(n, bool)) for k in ("dd_kirilim", "dd_kirilim_hacim", "ikili", "obo", "ucgen", "bayrak")}
    tepeler: list[tuple[int, float]] = []   # onaylı pivot tepeler (indeks, fiyat)
    dipler: list[tuple[int, float]] = []
    direnc = destek = np.nan
    # formasyon boyun çizgileri: (seviye, son_gecerli_indeks)
    ikili_al = ikili_sat = obo_al = obo_sat = None
    ucgen_al = ucgen_sat = None
    for i in range(n):
        j = i - K  # bu kapanışta onaylanan pivot
        if j >= 0:
            if pt[j]:
                tepeler.append((j, h[j]))
                direnc = h[j]
            if pdp[j]:
                dipler.append((j, l[j]))
                destek = l[j]
            if (pt[j] or pdp[j]) and len(tepeler) >= 2 and len(dipler) >= 2 and np.isfinite(a[i]):
                ikili_al, ikili_sat, obo_al, obo_sat, ucgen_al, ucgen_sat = _formasyonlar(
                    tepeler, dipler, a[i], i, ikili_al, ikili_sat, obo_al, obo_sat, ucgen_al, ucgen_sat)
        if i == 0:
            continue
        # destek/direnç kırılımı (kapanışla, ilk kırılım; seviye kırılınca tüketilir)
        hac_ok = np.isfinite(hacim_ort[i]) and v[i] > 1.5 * hacim_ort[i]
        if np.isfinite(direnc) and c[i] > direnc and c[i - 1] <= direnc:
            out["dd_kirilim"][0][i] = True
            out["dd_kirilim_hacim"][0][i] = hac_ok
            direnc = np.nan
        if np.isfinite(destek) and c[i] < destek and c[i - 1] >= destek:
            out["dd_kirilim"][1][i] = True
            out["dd_kirilim_hacim"][1][i] = hac_ok
            destek = np.nan
        for ad, kayit in (("ikili", ikili_al), ("obo", obo_al), ("ucgen", ucgen_al)):
            if kayit and i <= kayit[1] and c[i] > kayit[0] and c[i - 1] <= kayit[0]:
                out[ad][0][i] = True
        for ad, kayit in (("ikili", ikili_sat), ("obo", obo_sat), ("ucgen", ucgen_sat)):
            if kayit and i <= kayit[1] and c[i] < kayit[0] and c[i - 1] >= kayit[0]:
                out[ad][1][i] = True
        # tüketilen formasyonlar
        if ikili_al and c[i] > ikili_al[0]:
            ikili_al = None
        if ikili_sat and c[i] < ikili_sat[0]:
            ikili_sat = None
        if obo_al and c[i] > obo_al[0]:
            obo_al = None
        if obo_sat and c[i] < obo_sat[0]:
            obo_sat = None
        if ucgen_al and c[i] > ucgen_al[0]:
            ucgen_al = ucgen_sat = None
        if ucgen_sat and c[i] < ucgen_sat[0]:
            ucgen_al = ucgen_sat = None
    out["bayrak"] = _bayrak(h, l, c, a)
    return out


def _formasyonlar(tepeler, dipler, a, i, ikili_al, ikili_sat, obo_al, obo_sat, ucgen_al, ucgen_sat):
    """Son onaylı pivotlardan formasyon boyun/kenar çizgileri. Geçerlilik: 50 mum."""
    tol = 0.5 * a
    (t1i, t1), (t2i, t2) = tepeler[-2], tepeler[-1]
    (d1i, d1), (d2i, d2) = dipler[-2], dipler[-1]
    gec = i + 50
    # ikili tepe: iki tepe yakın, arada dip → boyun = aradaki en düşük dip
    arada_dip = [p for j, p in dipler if t1i < j < t2i]
    if abs(t1 - t2) <= tol and t2i - t1i >= 5 and arada_dip:
        ikili_sat = (min(arada_dip), gec)
    arada_tepe = [p for j, p in tepeler if d1i < j < d2i]
    if abs(d1 - d2) <= tol and d2i - d1i >= 5 and arada_tepe:
        ikili_al = (max(arada_tepe), gec)
    # OBO: üç tepe, ortası en yüksek, omuzlar yakın; boyun = aradaki iki dibin düşüğü
    if len(tepeler) >= 3:
        (s1i, s1), (bi, b), (s2i, s2) = tepeler[-3:]
        dl = [p for j, p in dipler if s1i < j < s2i]
        if b > s1 + tol and b > s2 + tol and abs(s1 - s2) <= 2 * tol and len(dl) >= 2:
            obo_sat = (min(dl), gec)
    if len(dipler) >= 3:
        (s1i, s1), (bi, b), (s2i, s2) = dipler[-3:]
        tl = [p for j, p in tepeler if s1i < j < s2i]
        if b < s1 - tol and b < s2 - tol and abs(s1 - s2) <= 2 * tol and len(tl) >= 2:
            obo_al = (max(tl), gec)
    # üçgen: son iki tepe ve iki dip
    duz_tepe, duz_dip = abs(t1 - t2) <= tol, abs(d1 - d2) <= tol
    alcalan_tepe, yukselen_dip = t2 < t1 - tol, d2 > d1 + tol
    if duz_tepe and yukselen_dip:      # yükselen üçgen → yukarı kırılım
        ucgen_al = (max(t1, t2), gec)
    elif duz_dip and alcalan_tepe:     # alçalan üçgen → aşağı kırılım
        ucgen_sat = (min(d1, d2), gec)
    elif alcalan_tepe and yukselen_dip:  # simetrik → iki yön
        ucgen_al, ucgen_sat = (t2, gec), (d2, gec)
    return ikili_al, ikili_sat, obo_al, obo_sat, ucgen_al, ucgen_sat


def _bayrak(h, l, c, a) -> tuple[np.ndarray, np.ndarray]:
    """Direk: 10 mumda ≥ 4×ATR hareket; ardından 5-15 mumluk konsolidasyon, aralığı direğin ≤ %50'si;
    konsolidasyon aralığının direk yönünde kapanışla kırılması."""
    n = len(c)
    al, sat = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(30, n):
        if not np.isfinite(a[i]):
            continue
        for w in (5, 10, 15):
            bas = i - w          # konsolidasyon: [bas, i-1]
            dir_bas = bas - 10
            if dir_bas < 0:
                continue
            direk = c[bas - 1] - c[dir_bas]
            kh, kl = h[bas:i].max(), l[bas:i].min()
            if abs(direk) < 4 * a[bas - 1] or (kh - kl) > 0.5 * abs(direk):
                continue
            if direk > 0 and c[i] > kh and c[i - 1] <= kh:
                al[i] = True
            elif direk < 0 and c[i] < kl and c[i - 1] >= kl:
                sat[i] = True
    return al, sat


# ------------------------------------------------------------------ sonuçlar (her mum için önceden)
def sonuclar(df: pd.DataFrame, yon: int, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Satır i'de sinyal olsaydı: i+1 açılışında giriş, stop 1.5×ATR(i), hedef k×stop.
    Döner: durum (1 doğru, 0 yanlış, -1 sonuçsuz/veri yok) ve maliyet sonrası R."""
    o = df["open"].to_numpy(float)
    a = atr_hesap(df, 14).to_numpy()
    giris = np.full(len(o), np.nan)
    giris[:-1] = o[1:]
    mesafe = STOP_ATR * a
    return yuru(df, yon, giris, giris - yon * mesafe, giris + yon * k * mesafe)


def seviye_hedefleri(df: pd.DataFrame, yon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """DENEYLER.md §5: her mum için seviye tabanlı (giriş, stop, hedef). Hedef yoksa NaN."""
    o, h, l = (df[x].to_numpy(float) for x in ("open", "high", "low"))
    a = atr_hesap(df, 14).to_numpy()
    n = len(o)
    pt, pdp = pivotlar(h, l)
    giris = np.full(n, np.nan)
    giris[:-1] = o[1:]
    stop = np.full(n, np.nan)
    hedef = np.full(n, np.nan)
    tepe_i = np.flatnonzero(pt)
    dip_i = np.flatnonzero(pdp)
    for i in range(n - 1):
        if not np.isfinite(a[i]):
            continue
        g, at = giris[i], a[i]
        # i'de bilinen pivotlar: j <= i-K, son 200 mum
        t = tepe_i[np.searchsorted(tepe_i, i - 200):np.searchsorted(tepe_i, i - K_PIVOT, side="right")]
        d = dip_i[np.searchsorted(dip_i, i - 200):np.searchsorted(dip_i, i - K_PIVOT, side="right")]
        tf, df_ = h[t], l[d]
        if yon == 1:
            ust = tf[tf >= g + at]
            alt = df_[df_ <= g - 0.5 * at]
            hedef[i] = ust.min() if len(ust) else np.nan
            st = (alt.max() - 0.25 * at) if len(alt) else g - STOP_ATR * at
            stop[i] = max(st, g - 3 * at)
        else:
            alt = df_[df_ <= g - at]
            ust = tf[tf >= g + 0.5 * at]
            hedef[i] = alt.max() if len(alt) else np.nan
            st = (ust.min() + 0.25 * at) if len(ust) else g + STOP_ATR * at
            stop[i] = min(st, g + 3 * at)
    return giris, stop, hedef


def yuru(df: pd.DataFrame, yon: int, giris: np.ndarray, stop: np.ndarray, hedef: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Her satır için verilen giriş/stop/hedefle ileri yürüyüş. R = (çıkış−giriş)/|giriş−stop| − maliyet."""
    o, h, l = (df[x].to_numpy(float) for x in ("open", "high", "low"))
    n = len(o)
    mesafe = np.abs(giris - stop)
    durum = np.full(n, -1, np.int8)
    cikis = np.full(n, np.nan)
    acik = np.isfinite(giris) & np.isfinite(hedef) & np.isfinite(stop) & (mesafe > 0)
    for j in range(1, UFUK + 1):
        idx = np.arange(n) + j
        gecerli = acik & (idx < n)
        if not gecerli.any():
            break
        ii = np.where(gecerli)[0]
        jj = idx[ii]
        acilis = o[jj]
        if yon == 1:
            bosluk_stop = (j > 1) & (acilis <= stop[ii])
            stop_v = l[jj] <= stop[ii]
            hedef_v = h[jj] >= hedef[ii]
        else:
            bosluk_stop = (j > 1) & (acilis >= stop[ii])
            stop_v = h[jj] >= stop[ii]
            hedef_v = l[jj] <= hedef[ii]
        kayip = stop_v | bosluk_stop
        kazanc = hedef_v & ~kayip
        s_i = ii[kayip]
        durum[s_i] = 0
        cikis[s_i] = np.where(bosluk_stop[kayip], acilis[kayip], stop[s_i])
        k_i = ii[kazanc]
        durum[k_i] = 1
        cikis[k_i] = hedef[k_i]
        acik[s_i] = False
        acik[k_i] = False
    with np.errstate(invalid="ignore", divide="ignore"):
        r = yon * (cikis - giris) / mesafe - 2 * MALIYET * giris / mesafe
    return durum, r


# ------------------------------------------------------------------ zaman dilimleri ve teyit
def trend(df: pd.DataFrame) -> np.ndarray:
    e20, e50 = ema(df["close"], 20), ema(df["close"], 50)
    t = np.where((df["close"] > e50) & (e20 > e50), 1, np.where((df["close"] < e50) & (e20 < e50), -1, 0))
    return np.where(e50.isna(), 0, t)


def hizala(kucuk_index: pd.DatetimeIndex, kucuk_tf: str, buyuk: pd.DataFrame, buyuk_tf: str, deger: np.ndarray) -> np.ndarray:
    """Büyük zaman diliminin yalnız TAMAMLANMIŞ mumundaki değeri küçük mumun kapanışına hizalar."""
    b = pd.Timedelta(milliseconds=veri.ARALIK_MS[kucuk_tf])
    B = pd.Timedelta(milliseconds=veri.ARALIK_MS[buyuk_tf])
    s = pd.Series(deger, index=buyuk.index + B)
    hedef = kucuk_index + b
    return s.reindex(s.index.union(hedef)).ffill().reindex(hedef).to_numpy()


# ------------------------------------------------------------------ araştırma
# İki bölüm: kısa (1s kaynak → 1s/4s/günlük; teyit 4s+günlük) ve uzun (günlük kaynak 2017+ → 3g/haftalık; teyit 3g+haftalık)
TEYIT_CIFT = {"4h": "1d", "3d": "1w"}
BASLANGIC_UZUN = pd.Timestamp("2019-01-01", tz="UTC")


def _sembol_isle(args):
    s, yol, mod = args
    df1 = veri._csv_oku(yol)
    df1 = df1[df1.index < pd.Timestamp("2026-11-01", tz="UTC")]
    sonuc = []
    if mod == "uzun":
        tfler = {"3d": veri.yeniden_ornekle(df1, "3d"), "1w": veri.yeniden_ornekle(df1, "1w")}
        bas, en_az = BASLANGIC_UZUN, 80
    else:
        tfler = {"1h": df1, "4h": veri.yeniden_ornekle(df1, "4h"), "1d": veri.yeniden_ornekle(df1, "1d")}
        bas, en_az = BASLANGIC, 300
    trendler = {tf: trend(d) for tf, d in tfler.items()}
    for tf, df in tfler.items():
        if len(df) < en_az:
            continue
        S = sinyaller(df)
        donem = (df.index >= bas)
        hold = df.index >= HOLDOUT
        if tf in TEYIT_CIFT:  # küçük zaman dilimi sinyali + kendi ve büyük zaman dilimi trendi aynı yönde (DENEYLER.md §6-7)
            b = TEYIT_CIFT[tf]
            tb = hizala(df.index, tf, tfler[b], b, trendler[b])
            teyit2_l = (trendler[tf] == 1) & (tb == 1)
            teyit2_s = (trendler[tf] == -1) & (tb == -1)
        if tf == "1h":
            t4 = hizala(df.index, "1h", tfler["4h"], "4h", trendler["4h"])
            t1d = hizala(df.index, "1h", tfler["1d"], "1d", trendler["1d"])
            teyit_l = (trendler["1h"] == 1) & (t4 == 1) & (t1d == 1)
            teyit_s = (trendler["1h"] == -1) & (t4 == -1) & (t1d == -1)
        for yon, yad in ((1, "long"), (-1, "short")):
            for k in HEDEFLER:
                durum, r = yuru(df, yon, *seviye_hedefleri(df, yon)) if k == "seviye" else sonuclar(df, yon, k)
                temel = donem & (durum >= 0)
                # rastgele giriş (her mum) — karşılaştırma tabanı
                kayit = {"sembol": s, "tf": tf, "yon": yad, "k": HEDEF_AD[k]}
                sonuc.append({**kayit, "sinyal": "_rastgele", **_say(durum, r, temel, hold)})
                for ad, (ml, ms) in S.items():
                    m = (ml if yon == 1 else ms) & temel
                    sonuc.append({**kayit, "sinyal": ad, **_say(durum, r, m, hold)})
                    if tf in TEYIT_CIFT:
                        mt = m & (teyit2_l if yon == 1 else teyit2_s)
                        sonuc.append({**kayit, "sinyal": ad + "+2tf", **_say(durum, r, mt, hold)})
                    if tf == "1h":
                        mt = m & (teyit_l if yon == 1 else teyit_s)
                        sonuc.append({**kayit, "sinyal": ad + "+3tf", **_say(durum, r, mt, hold)})
    return sonuc


def _say(durum, r, m, hold) -> dict:
    mh = m & hold
    return {"n": int(m.sum()), "dogru": int((durum[m] == 1).sum()), "r_top": float(np.nansum(r[m])),
            "r_kare": float(np.nansum(r[m] ** 2)), "n_h": int(mh.sum()), "dogru_h": int((durum[mh] == 1).sum()),
            "r_top_h": float(np.nansum(r[mh]))}


def uret(semboller: int | None = None, mod: str = "kisa") -> dict:
    """mod="kisa": 1s/4s/günlük (raporlar/formasyon.json); mod="uzun": 3g/haftalık (raporlar/formasyon_uzun.json)."""
    from concurrent.futures import ProcessPoolExecutor
    from .tarama import SPOT_ONBELLEK, varlik_turu

    t0 = time.time()
    isler = []
    for yol in sorted(SPOT_ONBELLEK.glob("*_1h.csv")):
        s = yol.name.split("_")[0]
        if s[:-4].endswith("B") and varlik_turu(s[:-4], np.array([2.0, 3.0])) != "kripto":
            continue
        if mod == "uzun":
            yol = SPOT_ONBELLEK / f"{s}_1d.csv"
            if not yol.exists():
                continue
        isler.append((s, yol, mod))
    if semboller:
        isler = isler[:semboller]
    satirlar = []
    with ProcessPoolExecutor() as ex:
        for x in ex.map(_sembol_isle, isler):
            satirlar += x
    t = pd.DataFrame(satirlar)
    g = t.groupby(["sinyal", "tf", "yon", "k"], as_index=False)[["n", "dogru", "r_top", "r_kare", "n_h", "dogru_h", "r_top_h"]].sum()
    taban = g[g["sinyal"] == "_rastgele"].set_index(["tf", "yon", "k"])
    kayitlar = []
    for x in g.itertuples(index=False):
        if x.sinyal == "_rastgele" or x.n == 0:
            continue
        tb = taban.loc[(x.tf, x.yon, x.k)]
        p0, p0h = tb.dogru / tb.n, tb.dogru_h / max(tb.n_h, 1)
        p = x.dogru / x.n
        ph = x.dogru_h / x.n_h if x.n_h else None
        ort_r = x.r_top / x.n
        sd = math.sqrt(max(x.r_kare / x.n - ort_r ** 2, 0))
        z = (p - p0) / math.sqrt(p0 * (1 - p0) / x.n)
        kabul = bool(x.n >= 300 and z >= 3.5 and ph is not None and x.n_h >= 30 and ph > p0h and ort_r > 0)
        kayitlar.append({"sinyal": x.sinyal, "ad": AD.get(x.sinyal.split("+")[0], (x.sinyal,))[0] + (" (3 zaman dilimi teyitli)" if x.sinyal.endswith("+3tf") else (" (4s + günlük teyitli)" if x.tf == "4h" else " (3g + haftalık teyitli)") if x.sinyal.endswith("+2tf") else ""),
                         "aile": AD.get(x.sinyal.split("+")[0], ("", "?"))[1], "tf": x.tf, "yon": x.yon, "k": x.k,
                         "n": int(x.n), "isabet": p, "rastgele": p0, "fark": p - p0, "z": z, "ort_r": ort_r,
                         "t_r": ort_r / (sd / math.sqrt(x.n)) if sd > 0 else 0.0,
                         "n_h": int(x.n_h), "isabet_h": ph, "rastgele_h": p0h, "ort_r_h": x.r_top_h / x.n_h if x.n_h else None,
                         "kabul": kabul})
    sonuc = {"olusturma": time.strftime("%Y-%m-%d", time.gmtime()), "sembol": len(isler),
             "donem": "2019-01 → 2026-10" if mod == "uzun" else "2021-01 → 2026-10", "holdout": "2025-01 → 2026-10",
             "tanim": f"Giriş: sinyalden sonraki mumun açılışı. Stop {STOP_ATR}×ATR(14), hedef k×stop. Önce hedef = doğru. "
                      f"{UFUK} mumda sonuçsuz kalanlar sayılmaz. Maliyet: %{MALIYET * 100:.2f}/yön (spot).",
             "taban": [{"tf": tf, "yon": y, "k": k, "isabet": r.dogru / r.n, "n": int(r.n)} for (tf, y, k), r in taban.iterrows()],
             "sinyaller": sorted(kayitlar, key=lambda x: (-x["isabet"]))}
    (KOK / "raporlar" / ("formasyon_uzun.json" if mod == "uzun" else "formasyon.json")).write_text(json.dumps(sonuc, ensure_ascii=False))
    log.info("formasyon araştırması: %d sembol, %.0fs", len(isler), time.time() - t0)
    return sonuc


def umut_verici(x: dict) -> bool:
    """DENEYLER.md §8 (sonuçlar görüldükten SONRA yazıldı, kullanıcı isteği): kabul kurallarının hepsini geçen ama
    300 olay eşiğinin altında kalan (100-299 olay) sinyaller. Bilgi etiketi; "doğrulanmış" sayılmaz."""
    return bool(not x["kabul"] and 100 <= x["n"] < 300 and x["z"] >= 3.5 and x["n_h"] >= 30
                and x["isabet_h"] is not None and x["isabet_h"] > x["rastgele_h"] and x["ort_r"] > 0)


def uygulama_istatistigi() -> dict:
    """Telefon/pano için kompakt istatistik: <depo kökü>/formasyon_istatistik.json (1 saatlik hariç; kullanıcı kararı)."""
    s, taban, meta = {}, {}, {}
    for ad in ("formasyon.json", "formasyon_uzun.json"):
        yol = KOK / "raporlar" / ad
        if not yol.exists():
            continue
        r = json.loads(yol.read_text())
        meta[ad] = {"donem": r["donem"], "sembol": r["sembol"], "olusturma": r["olusturma"]}
        for x in r["sinyaller"]:
            if x["tf"] == "1h":
                continue
            s[f'{x["sinyal"]}|{x["tf"]}|{x["yon"]}|{x["k"]}'] = [
                x["n"], round(x["isabet"], 4), round(x["rastgele"], 4), round(x["ort_r"], 4),
                None if x["isabet_h"] is None else round(x["isabet_h"], 4), int(x["kabul"]), int(umut_verici(x))]
        for t in r["taban"]:
            if t["tf"] != "1h":
                taban[f'{t["tf"]}|{t["yon"]}|{t["k"]}'] = round(t["isabet"], 4)
    out = {"kaynaklar": meta, "alanlar": ["n", "isabet", "rastgele", "ort_r", "isabet_holdout", "dogrulanmis", "umut_verici"],
           "taban": taban, "s": s}
    (KOK.parent / "formasyon_istatistik.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return out
