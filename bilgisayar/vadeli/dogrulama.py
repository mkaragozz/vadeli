"""Doğrulama: çoklu sembol, dilimli tutarlılık, parametre ızgarası, walk-forward, sağlık kontrolleri, alternatifler.

Ölçü birimi: getiri/düşüş metrikleri her sembol için ayrı alt hesapla (1000 USDT, %1 risk) hesaplanır.
Izgara ve walk-forward için işlem başına R (riske göre normalize kâr/zarar) kullanılır: hesap büyüklüğünden ve
bileşik büyümeden bağımsızdır, dilimlere bölmek kolaydır.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import veri
from .backtest import calistir, islem_istatistik
from .strateji import MaliyetParam, RiskParam, StratejiParam, hazirla

log = logging.getLogger(__name__)
KOK = Path(__file__).resolve().parent.parent
RAPOR_DIZINI = KOK / "raporlar"          # gerçek veri raporu (pano bunu gösterir)
DEMO_RAPOR_DIZINI = KOK / "raporlar_demo"  # sentetik deneme raporu gerçek raporun üstüne yazmasın

# ------------------------------------------------------------------ veri seti
_VERI: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
_METRIK: dict[str, pd.DataFrame] = {}
_BASLANGIC: pd.Timestamp | None = None  # işlemler yalnızca bu tarihten sonra (göstergeler öncesinde ısınır)


def veri_seti(semboller: list[str], bitis: str = "2026-10", demo: bool = False) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    if demo:
        return {s: (veri.rastgele_yuruyus(20_000, tohum=i, surukleme=0.00003 * (1 if i % 2 else -1)), pd.Series(dtype=float))
                for i, s in enumerate(semboller)}
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(8) as ex:  # indirme/okuma paralel
        sonuc = list(ex.map(lambda s: veri.gecmis_yukle(s, "2020-01", bitis), semboller))
    return dict(zip(semboller, sonuc))


def _yeniden_ornekle_set(d: dict, tf: str) -> dict:
    if tf == "1h":
        return d
    out = {}
    for s, (df, f) in d.items():
        out[s] = (veri.yeniden_ornekle(df, tf), f)
    return out


def _btc_rejim(d: dict, p: StratejiParam) -> pd.Series | None:
    if not p.btc_filtre:
        return None
    df = d["BTCUSDT"][0]
    return hazirla(df, replace(p, btc_filtre=False, hacim_kat=0, vol_min=0, vol_max=0, oi_teyit=False,
                               fonlama_esik=0.0, kalabalik_z=0.0, taker_teyit=False))["rejim"]


# ------------------------------------------------------------------ çekirdek çalıştırıcılar (süreç havuzunda)
def _is(args):
    sembol, p, r, m, kaydir, karistir = args
    df, f = _VERI[sembol]
    if p.tetik_tf != "1h":
        df = veri.yeniden_ornekle(df, p.tetik_tf)
    if karistir is not None:
        df = veri.getiri_karistir(df, karistir)
    btc = None
    btc_k = None
    if p.btc_filtre or p.rs_n:
        b = _VERI["BTCUSDT"][0]
        if p.tetik_tf != "1h":
            b = veri.yeniden_ornekle(b, p.tetik_tf)
        if p.rs_n and sembol != "BTCUSDT":
            btc_k = b["close"]
    if p.btc_filtre:
        btc = hazirla(b, replace(p, btc_filtre=False, hacim_kat=0, vol_min=0, vol_max=0, oi_teyit=False,
                                 fonlama_esik=0.0, kalabalik_z=0.0, taker_teyit=False))["rejim"]
    ek = None
    if p.turev_gerekli or _METRIK:
        from . import turev
        ek = turev.ozellikler(_METRIK.get(sembol), f, df.index, p.tetik_tf, oi_n=p.oi_n)
    s = calistir(df, p, r, m, fonlama=f, sembol=sembol, btc_rejim=btc, kaydir=kaydir, ek=ek, baslangic=_BASLANGIC,
                 btc_kapanis=btc_k)
    isl = s.islemler
    if not isl.empty:
        isl = isl[["giris_zaman", "cikis_zaman", "yon", "r", "net", "neden", "mum", "fonlama", "komisyon", "giris",
                   "ilk_stop", "cikis_fiyat"]].copy()
        isl["sembol"] = sembol
    gunluk = s.ozkaynak.resample("1D").last().dropna()
    return sembol, s.metrik, isl, gunluk


def _havuz_baslat(d, metrik=None, baslangic=None):
    global _VERI, _METRIK, _BASLANGIC
    _VERI = d
    _METRIK = metrik or {}
    _BASLANGIC = baslangic


def toplu_calistir(d: dict, p: StratejiParam, r: RiskParam, m: MaliyetParam, kaydir: int = 0,
                   karistir: int | None = None, ex: ProcessPoolExecutor | None = None) -> dict:
    isler = [(s, p, r, m, kaydir, karistir) for s in d]
    if ex is None:
        _havuz_baslat(d)
        sonuc = list(map(_is, isler))
    else:
        sonuc = list(ex.map(_is, isler))
    return {s: {"metrik": mt, "islemler": isl, "gunluk": g} for s, mt, isl, g in sonuc}


def havuz(d: dict, n: int | None = None, metrik: dict | None = None, baslangic=None) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(n or max(1, (os.cpu_count() or 2)), initializer=_havuz_baslat, initargs=(d, metrik, baslangic))


# ------------------------------------------------------------------ özetler
def portfoy_egrisi(sonuc: dict) -> pd.Series:
    """Eşit ağırlıklı portföy: her gün o gün aktif sembollerin günlük getirilerinin ortalaması."""
    getiriler = pd.DataFrame({s: v["gunluk"].pct_change() for s, v in sonuc.items() if len(v["gunluk"]) > 2})
    pr = getiriler.mean(axis=1, skipna=True).fillna(0.0)
    return (1 + pr).cumprod()


def egri_metrik(e: pd.Series) -> dict:
    if e.empty or len(e) < 3:
        return {}
    yil = (e.index[-1] - e.index[0]).days / 365.25
    gr = e.pct_change().dropna()
    dd = float((e / e.cummax() - 1).min())
    return {"toplam_getiri": float(e.iloc[-1] / e.iloc[0] - 1),
            "yillik_getiri": float((e.iloc[-1] / e.iloc[0]) ** (1 / max(yil, 1e-9)) - 1),
            "max_dusus": dd, "sharpe": float(gr.mean() / gr.std() * math.sqrt(365)) if gr.std() > 0 else 0.0}


def havuz_islemler(sonuc: dict) -> pd.DataFrame:
    parcalar = [v["islemler"] for v in sonuc.values() if v["islemler"] is not None and not v["islemler"].empty]
    return pd.concat(parcalar, ignore_index=True) if parcalar else pd.DataFrame()


def r_ozet(isl: pd.DataFrame) -> dict:
    """İşlem başına R özeti. t: ortalama R'nin sıfırdan farkı için t istatistiği (|t| < 2 ≈ anlamsız).
    Not: aynı anda açık, korelasyonlu işlemler yüzünden gerçek belirsizlik t'nin ima ettiğinden büyüktür."""
    if isl.empty:
        return {"islem": 0, "ort_r": 0.0, "toplam_r": 0.0, "kazanma": 0.0, "pf_r": 0.0, "t": 0.0, "sd": 0.0}
    k = isl.loc[isl["r"] > 0, "r"].sum()
    z = -isl.loc[isl["r"] <= 0, "r"].sum()
    sd = float(isl["r"].std()) if len(isl) > 2 else 0.0
    return {"islem": int(len(isl)), "ort_r": float(isl["r"].mean()), "toplam_r": float(isl["r"].sum()),
            "kazanma": float((isl["r"] > 0).mean()), "pf_r": float(k / z) if z > 0 else float("inf"),
            "t": float(isl["r"].mean() / (sd / math.sqrt(len(isl)))) if sd > 0 else 0.0, "sd": sd}


def sembol_tablosu(sonuc: dict) -> pd.DataFrame:
    satir = []
    for s, v in sonuc.items():
        mt = v["metrik"]
        if not mt:
            continue
        satir.append({"sembol": s, "baslangic": mt["baslangic"], "yil": mt["yil"], "toplam_getiri": mt["toplam_getiri"],
                      "yillik_getiri": mt["yillik_getiri"], "max_dusus": mt["max_dusus"], "sharpe": mt["sharpe"],
                      "islem": mt["islem"], "kazanma": mt["kazanma"], "profit_factor": mt["profit_factor"],
                      "ort_r": mt["ort_r"], "long_net": mt["long_net"], "short_net": mt["short_net"],
                      "likidasyon": mt["likidasyon"], "al_tut": mt["al_tut"], "fonlama": mt["fonlama_toplam"],
                      "komisyon": mt["komisyon_toplam"]})
    return pd.DataFrame(satir).sort_values("toplam_getiri", ascending=False) if satir else pd.DataFrame()


def genel_ozet(sonuc: dict) -> dict:
    tablo = sembol_tablosu(sonuc)
    isl = havuz_islemler(sonuc)
    e = portfoy_egrisi(sonuc)
    out = {"portfoy": egri_metrik(e), "havuz_r": r_ozet(isl), "sembol_sayisi": int(len(tablo))}
    if not tablo.empty:
        out.update({"karli_sembol_orani": float((tablo["toplam_getiri"] > 0).mean()),
                    "medyan_toplam_getiri": float(tablo["toplam_getiri"].median()),
                    "medyan_sharpe": float(tablo["sharpe"].median()),
                    "medyan_max_dusus": float(tablo["max_dusus"].median()),
                    "likidasyon": int(tablo["likidasyon"].sum())})
    if not isl.empty:
        out["istatistik"] = islem_istatistik(isl.assign(net=isl["net"]))
        for yon in ("LONG", "SHORT"):
            out[f"{yon.lower()}_r"] = r_ozet(isl[isl["yon"] == yon])
    return out


def dilim_tablosu(sonuc: dict, d: dict, p: StratejiParam, r: RiskParam, m: MaliyetParam,
                  dilimler: list[tuple[str, str]]) -> pd.DataFrame:
    """Her dilim ayrı: işlemleri giriş zamanına göre dilimle (R), portföy eğrisini dilimle (getiri/DD)."""
    isl = havuz_islemler(sonuc)
    e = portfoy_egrisi(sonuc)
    satir = []
    for bas, bit in dilimler:
        b, t = pd.Timestamp(bas, tz="UTC"), pd.Timestamp(bit, tz="UTC")
        parca = isl[(isl["giris_zaman"] >= b) & (isl["giris_zaman"] < t)] if not isl.empty else isl
        ed = e[(e.index >= b) & (e.index < t)]
        em = egri_metrik(ed / ed.iloc[0]) if len(ed) > 2 else {}
        sembol_r = parca.groupby("sembol")["r"].sum() if not parca.empty else pd.Series(dtype=float)
        satir.append({"dilim": f"{bas[:7]}..{bit[:7]}", **{f"r_{k}": v for k, v in r_ozet(parca).items()},
                      "portfoy_getiri": em.get("toplam_getiri", np.nan), "portfoy_dd": em.get("max_dusus", np.nan),
                      "portfoy_sharpe": em.get("sharpe", np.nan), "aktif_sembol": int(len(sembol_r)),
                      "karli_sembol_orani": float((sembol_r > 0).mean()) if len(sembol_r) else np.nan,
                      "long_r": float(parca.loc[parca["yon"] == "LONG", "r"].sum()) if not parca.empty else 0.0,
                      "short_r": float(parca.loc[parca["yon"] == "SHORT", "r"].sum()) if not parca.empty else 0.0})
    return pd.DataFrame(satir)


def yillik_dilimler(bas: int = 2020, bit: int = 2026, son: str = "2026-11-01") -> list[tuple[str, str]]:
    d = [(f"{y}-01-01", f"{y + 1}-01-01") for y in range(bas, bit)]
    d.append((f"{bit}-01-01", son))
    return d


# ------------------------------------------------------------------ ızgara ve walk-forward
VARSAYILAN_IZGARA = {"giris_n": [10, 20, 40, 55], "cikis_n": [5, 10, 20], "atr_kat": [2.0, 3.0, 4.0], "ema_n": [100, 200]}


def izgara(d: dict, temel: StratejiParam, r: RiskParam, m: MaliyetParam, ex, alanlar: dict | None = None) -> list[dict]:
    alanlar = alanlar or VARSAYILAN_IZGARA
    anahtarlar = list(alanlar)
    sonuclar = []
    for degerler in itertools.product(*alanlar.values()):
        kw = dict(zip(anahtarlar, degerler))
        if kw.get("cikis_n", 0) >= kw.get("giris_n", 999):
            continue
        p = replace(temel, **kw)
        t0 = time.time()
        sonuc = toplu_calistir(d, p, r, m, ex=ex)
        isl = havuz_islemler(sonuc)
        tablo = sembol_tablosu(sonuc)
        e = portfoy_egrisi(sonuc)
        sonuclar.append({"param": kw, "havuz_r": r_ozet(isl), "portfoy": egri_metrik(e),
                         "karli_sembol_orani": float((tablo["toplam_getiri"] > 0).mean()) if len(tablo) else 0.0,
                         "medyan_getiri": float(tablo["toplam_getiri"].median()) if len(tablo) else 0.0,
                         "islemler": isl[["giris_zaman", "sembol", "r", "yon"]] if not isl.empty else isl})
        log.info("ızgara %s: ortR=%.3f (%.1fs)", kw, sonuclar[-1]["havuz_r"]["ort_r"], time.time() - t0)
    return sonuclar


def izgara_ozet(sonuclar: list[dict]) -> dict:
    ort = np.array([x["havuz_r"]["ort_r"] for x in sonuclar])
    get = np.array([x["portfoy"].get("toplam_getiri", np.nan) for x in sonuclar])
    return {"kombinasyon": len(sonuclar), "karli_kombinasyon_orani_R": float((ort > 0).mean()),
            "karli_kombinasyon_orani_portfoy": float(np.nanmean(get > 0)),
            "medyan_ort_r": float(np.median(ort)), "medyan_portfoy_getiri": float(np.nanmedian(get)),
            "en_iyi_ort_r": float(ort.max()), "en_kotu_ort_r": float(ort.min())}


def walk_forward(sonuclar: list[dict], test_yillari: list[int], egitim_yil: int = 2,
                 varsayilan: dict | None = None) -> pd.DataFrame:
    """Her test yılı için: önceki `egitim_yil` yılda toplam R'si en yüksek kombinasyonu seç (sadece eğitim verisi),
    sonra seçilen kombinasyonun test yılındaki sonucunu ölç. Test yılı seçimde hiç kullanılmaz."""
    satir = []
    for y in test_yillari:
        eb, et = pd.Timestamp(f"{y - egitim_yil}-01-01", tz="UTC"), pd.Timestamp(f"{y}-01-01", tz="UTC")
        tb, tt = et, pd.Timestamp(f"{y + 1}-01-01", tz="UTC")

        def dilim(x, b, t):
            isl = x["islemler"]
            return isl[(isl["giris_zaman"] >= b) & (isl["giris_zaman"] < t)] if not isl.empty else isl

        puan = [(dilim(x, eb, et)["r"].mean() if len(dilim(x, eb, et)) >= 30 else -np.inf, i) for i, x in enumerate(sonuclar)]
        en_iyi = max(puan)[1]
        sec = sonuclar[en_iyi]
        test = r_ozet(dilim(sec, tb, tt))
        egitim = r_ozet(dilim(sec, eb, et))
        tum_test = [r_ozet(dilim(x, tb, tt))["ort_r"] for x in sonuclar]
        sat = {"test_yili": y, "egitim": f"{y - egitim_yil}-{y - 1}", "secilen": sec["param"],
               "egitim_ort_r": egitim["ort_r"], "test_ort_r": test["ort_r"], "test_toplam_r": test["toplam_r"],
               "test_islem": test["islem"], "test_kazanma": test["kazanma"],
               "test_tum_kombinasyon_medyan_r": float(np.median(tum_test)),
               "test_sirasi_yuzdelik": float((np.array(tum_test) <= test["ort_r"]).mean())}
        if varsayilan is not None:
            v = next((x for x in sonuclar if x["param"] == varsayilan), None)
            if v is not None:
                sat["varsayilan_test_ort_r"] = r_ozet(dilim(v, tb, tt))["ort_r"]
        satir.append(sat)
    return pd.DataFrame(satir)


# ------------------------------------------------------------------ rapor
def _json_uyumlu(x):
    if isinstance(x, dict):
        return {str(k): _json_uyumlu(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_uyumlu(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    return x


def kaydet(ad: str, nesne, dizin: Path | None = None) -> Path:
    dizin = dizin or RAPOR_DIZINI
    dizin.mkdir(parents=True, exist_ok=True)
    yol = dizin / ad
    if isinstance(nesne, pd.DataFrame):
        nesne.to_csv(yol, index=False)
    else:
        yol.write_text(json.dumps(_json_uyumlu(nesne), ensure_ascii=False, indent=1))
    return yol


def egri_json(e: pd.Series, adim: str = "1W") -> list[list]:
    e = e.resample(adim).last().dropna()
    return [[int(t.timestamp()), round(float(v), 5)] for t, v in e.items()]
