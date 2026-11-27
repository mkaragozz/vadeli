"""Strateji: sinyal üretimi ve risk/kaldıraç hesabı.

Backtest, canlı tarayıcı, pozisyon takibi ve geçmiş sinyal değerlendirmesi HEPSİ bu dosyadaki
`hazirla` ve `risk_hesapla` fonksiyonlarını kullanır. Kopya mantık yoktur.

Zaman kuralı (look-ahead yok):
  * Satır i = açılışı index[i] olan, KAPANMIŞ mum. Satır i'deki tüm değerler o mumun kapanışında bilinir.
  * Rejim: satır i'nin kapanış anına kadar TAMAMLANMIŞ son büyük (4s) mumun kapanışı ve EMA'sı.
  * Kanal: önceki N mumun en yükseği/düşüğü (`shift(1)`), mevcut mum dahil değil.
  * Sinyal satır i'de oluşur, işlem i+1 mumunun AÇILIŞINDA yapılır (backtest.py).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .veri import ARALIK_MS, yeniden_ornekle


@dataclass(frozen=True)
class StratejiParam:
    giris_n: int = 20          # kırılım kanalı (önceki N mumun en yükseği/düşüğü)
    cikis_n: int = 10          # karşı kanal çıkışı
    atr_n: int = 14
    atr_kat: float = 3.0       # takip eden stop = ATR * kat
    ema_n: int = 200           # rejim EMA'sı (rejim zaman diliminde)
    tetik_tf: str = "1h"
    rejim_tf: str = "4h"
    hacim_kat: float = 0.0     # >0 ise: kırılım mumunun USDT hacmi > kat * önceki 20 mum ortalaması
    vol_min: float = 0.0       # >0 ise: ATR/fiyat en az bu (çok sakin piyasayı ele)
    vol_max: float = 0.0       # >0 ise: ATR/fiyat en çok bu (aşırı oynak piyasayı ele)
    btc_filtre: bool = False   # True: LONG yalnız BTC rejimi +1, SHORT yalnız BTC rejimi -1 iken
    yon: str = "ikisi"         # "ikisi" | "long" | "short"
    # Türev konumlanma filtreleri (vadeli/turev.py; veri 2021-12'den beri). 0/False = kapalı.
    oi_teyit: bool = False     # kırılımda açık pozisyon son oi_n mumda artmış olmalı (yeni para girişi)
    oi_n: int = 6
    fonlama_esik: float = 0.0  # >0: LONG fonlama > eşik ise atla (kalabalık long), SHORT fonlama < -eşik ise atla
    kalabalik_z: float = 0.0   # >0: LONG long/short hesap oranı z > eşik ise atla, SHORT z < -eşik ise atla
    taker_teyit: bool = False  # LONG taker alım/satım > 1, SHORT < 1 olmalı
    # Geliştirme turu 2 (DENEYLER.md §2). 0 = kapalı.
    rs_n: int = 0              # >0: LONG yalnız coinin son rs_n mumluk getirisi BTC'ninkinden yüksekse (SHORT tersi)
    basabas_r: float = 0.0     # >0: kapanış lehte bu kadar R gidince stop girişe (+maliyet) çekilir

    @property
    def turev_gerekli(self) -> bool:
        return bool(self.oi_teyit or self.fonlama_esik or self.kalabalik_z or self.taker_teyit)

    @property
    def surum(self) -> str:
        """Parametre sürümü: aynı parametre = aynı kısa özet (sinyal kayıtlarında saklanır).
        Varsayılan değerdeki alanlar özete girmez: yeni alan eklemek eski sürümleri değiştirmez."""
        varsayilan = _VARSAYILAN
        d = {k: v for k, v in asdict(self).items() if k in _ESKI_ALANLAR or v != varsayilan.get(k)}
        return "p" + hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:8]

    def ozet(self) -> str:
        s = f"{self.tetik_tf} tetik {self.giris_n}/{self.cikis_n}, ATR{self.atr_n}x{self.atr_kat}, EMA{self.ema_n}({self.rejim_tf})"
        if self.hacim_kat:
            s += f", hacim>{self.hacim_kat}x"
        if self.vol_min or self.vol_max:
            s += f", vol[{self.vol_min:.3f},{self.vol_max:.3f}]"
        if self.btc_filtre:
            s += ", BTC rejim"
        if self.yon != "ikisi":
            s += f", sadece {self.yon}"
        if self.oi_teyit:
            s += f", OI↑({self.oi_n})"
        if self.fonlama_esik:
            s += f", fonlama<{self.fonlama_esik * 100:.2f}%"
        if self.kalabalik_z:
            s += f", kalabalık z<{self.kalabalik_z}"
        if self.taker_teyit:
            s += ", taker teyit"
        if self.rs_n:
            s += f", RS>BTC({self.rs_n})"
        if self.basabas_r:
            s += f", başabaş@{self.basabas_r}R"
        return s


_ESKI_ALANLAR = {"giris_n", "cikis_n", "atr_n", "atr_kat", "ema_n", "tetik_tf", "rejim_tf", "hacim_kat", "vol_min",
                 "vol_max", "btc_filtre", "yon"}


_VARSAYILAN = asdict(StratejiParam())


@dataclass(frozen=True)
class RiskParam:
    hesap: float = 1000.0      # USDT
    risk_yuzde: float = 1.0    # işlem başına stopa kadar riske edilen hesap yüzdesi
    max_kaldirac: float = 5.0  # kullanıcı tavanı
    mmr: float = 0.005         # bakım teminatı oranı (Binance kademe 1 ~%0.4-1; temkinli)
    liq_oran: float = 0.5      # stop mesafesi <= likidasyon mesafesi * bu oran


@dataclass(frozen=True)
class MaliyetParam:
    komisyon: float = 0.0005   # taker, yön başına
    kayma: float = 0.0003      # yön başına
    fonlama_8s: float = 0.0001 # sabit modda 8 saatte bir, iki yönde de ÖDENİR (temkinli)
    fonlama_mod: str = "gercek"  # "gercek" (tarihsel oranlar, işaretli) | "sabit" | "yok"

    @property
    def tek_yon(self) -> float:
        return self.komisyon + self.kayma


# ------------------------------------------------------------------ göstergeler
def ema(s: pd.Series, n: int) -> pd.Series:
    """Standart EMA (alpha=2/(n+1)); ilk n-1 değer NaN (ısınma)."""
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR. Satır i değeri mum i'nin kapanışında bilinir."""
    onceki = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - onceki).abs(), (df["low"] - onceki).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rejim_hizala(df: pd.DataFrame, tetik_tf: str, rejim_tf: str, ema_n: int) -> pd.DataFrame:
    """Rejim zaman dilimindeki kapanış ve EMA'yı tetik mumlarına hizalar.

    Büyük mum (açılış T, süre B) T+B anında kapanır. Tetik mumu i (açılış t, süre b) t+b'de kapanır.
    i satırına, kapanışı <= t+b olan son büyük mum atanır. Böylece oluşmakta olan 4s mum asla görülmez.
    """
    b = pd.Timedelta(milliseconds=ARALIK_MS[tetik_tf])
    if rejim_tf == tetik_tf:
        k = df["close"]
        return pd.DataFrame({"kapanis_r": k, "ema_r": ema(k, ema_n)}, index=df.index)
    buyuk = yeniden_ornekle(df, rejim_tf)
    B = pd.Timedelta(milliseconds=ARALIK_MS[rejim_tf])
    r = pd.DataFrame({"kapanis_r": buyuk["close"], "ema_r": ema(buyuk["close"], ema_n)})
    r.index = r.index + B  # büyük mumun KAPANIŞ zamanı
    hedef = df.index + b   # tetik mumlarının kapanış zamanı
    hiz = r.reindex(r.index.union(hedef)).ffill().reindex(hedef)
    hiz.index = df.index
    return hiz


def hazirla(df: pd.DataFrame, p: StratejiParam = StratejiParam(), btc_rejim: pd.Series | None = None,
            ek: pd.DataFrame | None = None, btc_kapanis: pd.Series | None = None) -> pd.DataFrame:
    """Tek ve ortak sinyal fonksiyonu. Girdi: kapanmış mumlar (tetik_tf). Çıktı: göstergeler + sinyaller.

    Sütunlar:
      rejim (+1/-1/0), kanal_ust/kanal_alt (giriş), cikis_ust/cikis_alt, atr,
      long_tetik/short_tetik (ham kırılım + rejim), long_sinyal/short_sinyal (filtreler dahil),
      long_yeni/short_yeni (önceki mumda tetik yoksa True), long_cikis/short_cikis (karşı kanal kırılımı),
      long_yakin/short_yakin (kanala 0.5 ATR'den az kaldı, henüz kırılmadı)
    `btc_kapanis`: göreli güç filtresi (rs_n) için BTC kapanışları (aynı zaman dilimi). None = filtre nötr
    (BTC'nin kendisi için kasıtlı olarak None verilir).
    """
    out = df[["open", "high", "low", "close", "volume", "quote_volume"]].copy()
    r = rejim_hizala(df, p.tetik_tf, p.rejim_tf, p.ema_n)
    out["kapanis_r"] = r["kapanis_r"]
    out["ema_r"] = r["ema_r"]
    rejim = np.where(out["kapanis_r"] > out["ema_r"], 1, np.where(out["kapanis_r"] < out["ema_r"], -1, 0))
    rejim = np.where(out["ema_r"].isna(), 0, rejim)
    out["rejim"] = rejim.astype(int)

    out["kanal_ust"] = df["high"].rolling(p.giris_n).max().shift(1)
    out["kanal_alt"] = df["low"].rolling(p.giris_n).min().shift(1)
    out["cikis_ust"] = df["high"].rolling(p.cikis_n).max().shift(1)
    out["cikis_alt"] = df["low"].rolling(p.cikis_n).min().shift(1)
    out["atr"] = atr(df, p.atr_n)

    kirilim_l = df["close"] > out["kanal_ust"]
    kirilim_s = df["close"] < out["kanal_alt"]
    out["long_tetik"] = kirilim_l & (out["rejim"] == 1)
    out["short_tetik"] = kirilim_s & (out["rejim"] == -1)

    filtre = pd.Series(True, index=df.index) & out["atr"].notna()
    if p.hacim_kat > 0:
        ort = df["quote_volume"].rolling(20).mean().shift(1)
        filtre &= df["quote_volume"] > p.hacim_kat * ort
    atr_oran = out["atr"] / df["close"]
    if p.vol_min > 0:
        filtre &= atr_oran >= p.vol_min
    if p.vol_max > 0:
        filtre &= atr_oran <= p.vol_max
    filtre_l = filtre.copy()
    filtre_s = filtre.copy()
    if p.btc_filtre:
        if btc_rejim is None:
            raise ValueError("btc_filtre=True için btc_rejim serisi gerekli")
        b = btc_rejim.reindex(df.index).ffill().fillna(0)
        filtre_l &= b == 1
        filtre_s &= b == -1
    if ek is not None:  # türev özellikleri (turev.ozellikler, aynı index'e hizalı, look-ahead'siz)
        for c in ek.columns:
            out[c] = ek[c].reindex(df.index)
    if p.turev_gerekli:
        if ek is None:
            raise ValueError("Türev filtreleri için ek (turev.ozellikler) gerekli")
        if p.oi_teyit:  # teyit filtresi: veri yoksa işlem yok
            k = (out["oi_deg"] > 0).fillna(False)
            filtre_l &= k
            filtre_s &= k
        if p.fonlama_esik:  # veto filtresi: veri yoksa engellemez
            f = out["fonlama"]
            filtre_l &= ~(f > p.fonlama_esik).fillna(False)
            filtre_s &= ~(f < -p.fonlama_esik).fillna(False)
        if p.kalabalik_z:
            z = out["ls_z"]
            filtre_l &= ~(z > p.kalabalik_z).fillna(False)
            filtre_s &= ~(z < -p.kalabalik_z).fillna(False)
        if p.taker_teyit:
            t = out["taker"]
            filtre_l &= (t > 1).fillna(False)
            filtre_s &= (t < 1).fillna(False)
    if p.rs_n > 0 and btc_kapanis is not None:
        b = btc_kapanis.reindex(df.index)
        rs = (df["close"] / df["close"].shift(p.rs_n)) - (b / b.shift(p.rs_n))
        out["rs"] = rs
        filtre_l &= (rs > 0).fillna(False)
        filtre_s &= (rs < 0).fillna(False)
    if p.yon == "short":
        filtre_l &= False
    if p.yon == "long":
        filtre_s &= False

    out["long_sinyal"] = out["long_tetik"] & filtre_l
    out["short_sinyal"] = out["short_tetik"] & filtre_s
    out["long_yeni"] = out["long_sinyal"] & ~out["long_tetik"].shift(1, fill_value=False)
    out["short_yeni"] = out["short_sinyal"] & ~out["short_tetik"].shift(1, fill_value=False)
    out["long_cikis"] = df["close"] < out["cikis_alt"]
    out["short_cikis"] = df["close"] > out["cikis_ust"]
    yarim = 0.5 * out["atr"]
    out["long_yakin"] = (out["rejim"] == 1) & ~kirilim_l & ((out["kanal_ust"] - df["close"]) <= yarim)
    out["short_yakin"] = (out["rejim"] == -1) & ~kirilim_s & ((df["close"] - out["kanal_alt"]) <= yarim)
    for c in ["long_tetik", "short_tetik", "long_sinyal", "short_sinyal", "long_yeni", "short_yeni",
              "long_cikis", "short_cikis", "long_yakin", "short_yakin"]:
        out[c] = out[c].fillna(False).astype(bool)
    return out


# ------------------------------------------------------------------ risk / kaldıraç
def likidasyon_fiyati(giris: float, yon: int, kaldirac: float, mmr: float) -> float:
    """İzole marjin yaklaşık likidasyon fiyatı (Binance formülünün sade hali; ücretler hariç)."""
    if yon == 1:
        return giris * (1 - 1 / kaldirac + mmr)
    return giris * (1 + 1 / kaldirac - mmr)


def ilk_stop(giris: float, yon: int, atr_degeri: float, p: StratejiParam) -> float:
    return giris - yon * p.atr_kat * atr_degeri


def risk_hesapla(giris: float, stop: float, yon: int, r: RiskParam, m: MaliyetParam,
                 ozkaynak: float | None = None) -> dict:
    """Pozisyon büyüklüğü, kaldıraç, teminat ve likidasyon.

    * Risk: özkaynak * risk% (stop + iki yön maliyet dahil) -> pozisyon büyüklüğü (notional)
    * Kaldıraç: stop mesafesi <= likidasyon mesafesinin liq_oran'ı olacak en yüksek tam sayı, kullanıcı tavanıyla sınırlı.
      Likidasyon mesafesi ~ 1/k - mmr  =>  k <= 1 / (d/liq_oran + mmr)
    * Kaldıraç RİSKİ DEĞİŞTİRMEZ; sadece bağlanan teminatı (notional/k) belirler.
    """
    ozkaynak = r.hesap if ozkaynak is None else ozkaynak
    d = abs(giris - stop) / giris
    if not (d > 0 and math.isfinite(d)):
        raise ValueError("Stop mesafesi sıfır/geçersiz")
    risk_usdt = ozkaynak * r.risk_yuzde / 100.0
    notional = risk_usdt / (d + 2 * m.tek_yon)
    k_liq = 1.0 / (d / r.liq_oran + r.mmr)
    kaldirac = max(1.0, min(r.max_kaldirac, math.floor(k_liq)))
    # Teminat özkaynağı aşamaz: gerekirse pozisyon küçülür (risk de küçülür)
    notional = min(notional, ozkaynak * kaldirac * 0.95)
    teminat = notional / kaldirac
    liq = likidasyon_fiyati(giris, yon, kaldirac, r.mmr)
    liq_mesafe = abs(giris - liq) / giris
    return {
        "giris": giris, "stop": stop, "stop_yuzde": d * 100, "kaldirac": kaldirac, "notional": notional,
        "adet": notional / giris, "teminat": teminat, "likidasyon": liq, "liq_yuzde": liq_mesafe * 100,
        "risk_usdt": notional * (d + 2 * m.tek_yon), "stop_liq_orani": d / liq_mesafe if liq_mesafe > 0 else float("inf"),
    }


def son_sinyaller(h: pd.DataFrame, r: RiskParam, m: MaliyetParam, p: StratejiParam) -> list[dict]:
    """Hazırlanmış verinin SON (kapanmış) mumundaki sinyaller/yaklaşanlar. Canlı tarayıcı bunu kullanır.
    Gösterilen fiyat son kapanıştır; gerçek giriş sonraki mumun açılışında olur."""
    if h.empty:
        return []
    son = h.iloc[-1]
    sonuc = []
    for yon, ad in ((1, "LONG"), (-1, "SHORT")):
        on = "long" if yon == 1 else "short"
        tur = "sinyal" if son[f"{on}_sinyal"] else ("yaklasan" if son[f"{on}_yakin"] else None)
        if tur is None or not np.isfinite(son["atr"]):
            continue
        fiyat = float(son["close"])
        stop = ilk_stop(fiyat, yon, float(son["atr"]), p)
        if tur == "yaklasan":
            seviye = float(son["kanal_ust"] if yon == 1 else son["kanal_alt"])
            fiyat_ref = seviye
            stop = ilk_stop(seviye, yon, float(son["atr"]), p)
        else:
            fiyat_ref = fiyat
        rk = risk_hesapla(fiyat_ref, stop, yon, r, m)
        sonuc.append({
            "tur": tur, "yon": ad, "zaman": h.index[-1].isoformat(), "fiyat": fiyat, "seviye": fiyat_ref,
            "atr": float(son["atr"]), "rejim": int(son["rejim"]), "ema_r": float(son["ema_r"]),
            "kapanis_r": float(son["kapanis_r"]), "yeni": bool(son[f"{on}_yeni"]) if tur == "sinyal" else False,
            "kanal_ust": float(son["kanal_ust"]), "kanal_alt": float(son["kanal_alt"]),
            "param_surum": p.surum, **rk,
            **{k: (float(son[k]) if pd.notna(son[k]) else None) for k in ("oi_deg", "fonlama", "ls_z", "taker") if k in son.index},
        })
    return sonuc
