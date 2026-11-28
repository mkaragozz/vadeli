"""Tablo temel modelleri (TabPFN ailesi: TabICL, TabDPT, Mitra; lisans onayı gelirse TabPFN) ile skor araştırması.
DENEYLER.md §9 (ön kayıtlı). Dört görev × dört zaman dilimi; zaman sıralı (geleceğe bakmayan) değerlendirme.

  A  sinyal kalite skoru   satır = formasyon/kırılım/indikatör sinyali, etiket = 1:1 hedef stoptan önce
  B  yön                   satır = (coin, mum) H aralıkla, etiket = H mum sonra daha yüksek
  C  hacim durumu sonrası  satır = günlük hacim patlaması/artan/kuruma olayı, etiket = 30 gün getiri > 0
  D  seviye kırılımı       satır = destek/direnç kırılımı, etiket = sonraki seviyeye stoptan önce

Özellikler yalnız satırın mum kapanışında bilinen veriden (`ozellikler`); telefon sürümü aynı hesabı JS'te yapar.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import formasyon as F
from . import veri
from .strateji import ema

log = logging.getLogger(__name__)
KOK = Path(__file__).resolve().parent.parent
MOBIL = KOK.parent  # telefon uygulaması depo kökünde
SPOT = veri.VARSAYILAN_ONBELLEK / "spot"
UST_TF = {"4h": "1d", "1d": "1w", "3d": "1w", "1w": None}
YON_H = {"4h": 6, "1d": 7, "3d": 5, "1w": 4}
TEST_YILLARI = {"4h": [2023, 2024, 2025, 2026], "1d": [2023, 2024, 2025, 2026],
                "3d": [2021, 2022, 2023, 2024, 2025, 2026], "1w": [2021, 2022, 2023, 2024, 2025, 2026]}
SINYAL_KOD = {ad: i for i, ad in enumerate(F.AD)}
BAGLAM = 3000
TEST_EN_COK = 2000
OZELLIK = ["rsi", "trend", "trend_ust", "atr_oran", "g5", "g20", "g60", "hacim_oran", "direnc_atr", "destek_atr",
           "kanal_konum", "btc_trend", "btc_g20", "zirveden"]


# ------------------------------------------------------------------ veri
def mumlar(sembol: str, tf: str) -> pd.DataFrame | None:
    """4s: 1s spot arşivinden; günlük/3g/haftalık: günlük spot arşivinden (2017+). Analiz sonu 2026-10."""
    if tf == "4h":
        yol = SPOT / f"{sembol}_1h.csv"
        if not yol.exists():
            return None
        df = veri.yeniden_ornekle(veri._csv_oku(yol), "4h")
    else:
        yol = SPOT / f"{sembol}_1d.csv"
        if not yol.exists():
            return None
        df = veri._csv_oku(yol)
        df = df if tf == "1d" else veri.yeniden_ornekle(df, tf)
    return df[df.index < pd.Timestamp("2026-11-01", tz="UTC")]


def _yakin_seviyeler(h: np.ndarray, l: np.ndarray, c: np.ndarray, a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Her mum için en yakın onaylı (sağında 5 mum kapanmış) pivot tepe üstte / dip altta, son 200 mum, ATR cinsinden."""
    n = len(c)
    pt, pdp = F.pivotlar(h, l)
    ti, di = np.flatnonzero(pt), np.flatnonzero(pdp)
    dr, ds = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(n):
        if not (a[i] > 0):
            continue
        t = ti[np.searchsorted(ti, i - 200):np.searchsorted(ti, i - F.K_PIVOT, side="right")]
        d = di[np.searchsorted(di, i - 200):np.searchsorted(di, i - F.K_PIVOT, side="right")]
        ust = h[t][h[t] > c[i]]
        alt = l[d][l[d] < c[i]]
        dr[i] = ((ust.min() - c[i]) / a[i]) if len(ust) else 10.0
        ds[i] = ((c[i] - alt.max()) / a[i]) if len(alt) else 10.0
    return np.minimum(dr, 10.0), np.minimum(ds, 10.0)


def ozellikler(df: pd.DataFrame, ust: pd.DataFrame | None, tf: str, btc: pd.DataFrame | None) -> pd.DataFrame:
    """Satır i = mum i'nin kapanışında bilinen sayısal özellikler (look-ahead yok)."""
    c = df["close"]
    a = F.atr_hesap(df, 14)
    out = pd.DataFrame(index=df.index)
    out["rsi"] = F.rsi(c)
    out["trend"] = F.trend(df)
    out["trend_ust"] = (F.hizala(df.index, tf, ust, UST_TF[tf], F.trend(ust)) if ust is not None and len(ust) > 60
                        else np.nan)
    out["atr_oran"] = a / c
    for n in (5, 20, 60):
        out[f"g{n}"] = c / c.shift(n) - 1
    out["hacim_oran"] = df["quote_volume"] / df["quote_volume"].rolling(20).mean().shift(1)
    dr, ds = _yakin_seviyeler(df["high"].to_numpy(float), df["low"].to_numpy(float), c.to_numpy(float), a.to_numpy(float))
    out["direnc_atr"], out["destek_atr"] = dr, ds
    hi, lo = df["high"].rolling(20).max(), df["low"].rolling(20).min()
    out["kanal_konum"] = (c - lo) / (hi - lo).replace(0, np.nan)
    if btc is not None and len(btc):
        bt = pd.Series(F.trend(btc), index=btc.index)
        bg = btc["close"] / btc["close"].shift(20) - 1
        out["btc_trend"] = bt.reindex(df.index)
        out["btc_g20"] = bg.reindex(df.index)
    else:
        out["btc_trend"] = out["btc_g20"] = np.nan
    out["zirveden"] = c / c.rolling(250, min_periods=250).max() - 1   # telefon 500 mum çeker: 250 mumluk zirve hesaplanabilir
    out["hurst"] = hurst(c)
    out["perm_entropi"] = perm_entropi(c)
    return out.replace([np.inf, -np.inf], np.nan)


def _sembol_satirlari(args) -> dict[str, pd.DataFrame]:
    s, tf = args
    df = mumlar(s, tf)
    if df is None or len(df) < 120:
        return {}
    ust = mumlar(s, UST_TF[tf]) if UST_TF[tf] else None
    btc = mumlar("BTCUSDT", tf)
    X = ozellikler(df, ust, tf, btc)
    S = F.sinyaller(df)
    out: dict[str, list] = {"A": [], "B": [], "C": [], "D": []}
    # A ve D: sinyal olayları
    for yon in (1, -1):
        d11, r11 = F.sonuclar(df, yon, 1.0)
        dsv, rsv = F.yuru(df, yon, *F.seviye_hedefleri(df, yon))
        for ad, (ml, ms) in S.items():
            m = (ml if yon == 1 else ms) & (d11 >= 0)
            if m.any():
                t = X[m].copy()
                t["sinyal"], t["yon"], t["y"], t["r"] = SINYAL_KOD[ad], yon, (d11[m] == 1).astype(int), r11[m]
                out["A"].append(t)
            if ad == "dd_kirilim":
                m = (ml if yon == 1 else ms) & (dsv >= 0)
                if m.any():
                    t = X[m].copy()
                    t["yon"], t["y"], t["r"] = yon, (dsv[m] == 1).astype(int), rsv[m]
                    out["D"].append(t)
    # B: yön, H aralıkla
    H = YON_H[tf]
    ileri = df["close"].shift(-H) / df["close"] - 1
    t = X.iloc[::H].copy()
    t["y"] = (ileri.iloc[::H] > 0).astype(int)
    t["r"] = ileri.iloc[::H]
    out["B"].append(t[ileri.iloc[::H].notna()])
    # C: hacim durumu (yalnız günlük)
    if tf == "1d":
        from . import tarama
        o = tarama.olcu_serileri(df)
        sn = tarama.siniflar(o, json.loads((MOBIL / "tarama_istatistik.json").read_text())["esikler"])
        g30 = df["close"].shift(-30) / df["close"] - 1
        for k, ad in enumerate(("patlama", "artan", "kuruma")):
            m = sn[ad] & g30.notna() & (o["gun"] >= 90)
            if m.any():
                t = X[m.to_numpy()].copy()
                t["sinif"], t["y"], t["r"] = k, (g30[m] > 0).astype(int).to_numpy(), g30[m].to_numpy()
                out["C"].append(t)
    son = {}
    for g, parca in out.items():
        if parca:
            x = pd.concat(parca)
            x["sembol"] = s
            son[g] = x
    return son


def veri_seti(tf: str, semboller: list[str] | None = None) -> dict[str, pd.DataFrame]:
    from concurrent.futures import ProcessPoolExecutor
    from .tarama import varlik_turu

    semboller = semboller or sorted(p.name.split("_")[0] for p in SPOT.glob("*_1d.csv")
                                    if not (p.name[:-11].endswith("B") and varlik_turu(p.name[:-11], np.array([2., 3.])) != "kripto"))
    with ProcessPoolExecutor() as ex:
        sonuc = list(ex.map(_sembol_satirlari, [(s, tf) for s in semboller]))
    gorev = {}
    for g in "ABCD":
        p = [x[g] for x in sonuc if g in x]
        if p:
            gorev[g] = pd.concat(p).sort_index()
    return gorev


# ------------------------------------------------------------------ modeller
KAOS_OZELLIK = ["hurst", "perm_entropi"]
KAOS = False  # DENEYLER.md §10: True iken modeller kaos özelliklerini de kullanır (uret_kaos)


def sutunlar(g: str) -> list[str]:
    return OZELLIK + (KAOS_OZELLIK if KAOS else []) + {"A": ["sinyal", "yon"], "B": [], "C": ["sinif"], "D": ["yon"]}[g]


def hurst(c: pd.Series, pencere: int = 100, gecikmeler=range(1, 11)) -> pd.Series:
    """Varyans ölçekleme Hurst üssü (DENEYLER.md §10): son `pencere` mumdaki τ gecikmeli log fiyat farklarının kareler
    ortalamasının kökü τ^H ile ölçeklenir; H = log RMS'nin log τ'ya regresyon eğimi. Ortalama çıkarılmaz (örtüşen farklarda
    ortalama çıkarmak uzun gecikmeleri küçültüp H'yi aşağı çeker; rastgele yürüyüşte 0.39 yerine 0.49 verir).
    Satır t yalnız t ve öncesini kullanır."""
    lp = np.log(c)
    lt = np.log(np.array(list(gecikmeler), dtype=float))
    xm = lt - lt.mean()
    Y = np.vstack([np.log(np.sqrt(((lp - lp.shift(t)) ** 2).rolling(pencere, min_periods=pencere).mean())).to_numpy()
                   for t in gecikmeler])                  # gecikme × zaman
    with np.errstate(invalid="ignore"):
        egim = (xm[:, None] * (Y - Y.mean(axis=0))).sum(axis=0) / (xm ** 2).sum()
    return pd.Series(egim, index=c.index).replace([np.inf, -np.inf], np.nan)


def perm_entropi(c: pd.Series, pencere: int = 100, sira: int = 3) -> pd.Series:
    """Permütasyon entropisi (Bandt-Pompe, sıra 3), 0-1 arası normalleştirilmiş; son `pencere` mumun desenleri."""
    x = c.to_numpy(float)
    n = len(x)
    desen = np.full(n, -1)
    if n >= sira:
        from numpy.lib.stride_tricks import sliding_window_view as sw
        w = sw(x, sira)
        kod = np.argsort(w, axis=1, kind="stable")
        desen[sira - 1:] = (kod * np.array([sira ** i for i in range(sira)])).sum(axis=1)
    say = pd.get_dummies(pd.Series(desen, index=c.index)).drop(columns=[-1], errors="ignore").astype(float)
    adet = say.rolling(pencere - sira + 1, min_periods=pencere - sira + 1).sum()
    p = adet.div(adet.sum(axis=1), axis=0)
    h = -(p * np.log(p.where(p > 0))).sum(axis=1, min_count=1)
    return (h / np.log(math.factorial(sira))).where(adet.notna().all(axis=1))


def _taban(tr: pd.DataFrame, te: pd.DataFrame, g: str) -> np.ndarray:
    """Uygulamadaki mevcut yöntem: eğitimde aynı gruptaki (sinyal türü+yön / sınıf / yön) ortalama isabet."""
    anahtar = {"A": ["sinyal", "yon"], "B": [], "C": ["sinif"], "D": ["yon"]}[g]
    if not anahtar:
        return np.full(len(te), tr["y"].mean())
    ort = tr.groupby(anahtar)["y"].agg(["sum", "count"])
    oran = (ort["sum"] + 1) / (ort["count"] + 2)
    return te[anahtar].apply(tuple, axis=1).map(lambda k: oran.get(k if len(k) > 1 else k[0], tr["y"].mean())).to_numpy(float)


def _model(ad: str):
    if ad == "lojistik":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(C=0.5, max_iter=500))
    if ad == "lightgbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    if ad == "tabicl":
        from tabicl import TabICLClassifier
        return TabICLClassifier(device="cpu", random_state=0)
    if ad == "tabdpt":
        from tabdpt import TabDPTClassifier
        return TabDPTClassifier(device="cpu", compile=False)
    if ad == "mitra":
        from autogluon.tabular.models.mitra.sklearn_interface import MitraClassifier
        return MitraClassifier(device="cpu", fine_tune=False)
    if ad == "tabpfn":
        from tabpfn import TabPFNClassifier
        return TabPFNClassifier(device="cpu")
    raise ValueError(ad)


BAGLAM_MODELLERI = ("tabicl", "tabdpt", "mitra", "tabpfn")


def tahmin(ad: str, tr: pd.DataFrame, te: pd.DataFrame, g: str, tohum: int = 0) -> np.ndarray:
    if ad == "taban":
        return _taban(tr, te, g)
    cols = sutunlar(g)
    if ad in BAGLAM_MODELLERI:
        tr = tr.iloc[-BAGLAM:]                  # en yeni bağlam (zaman sıralı)
        Xtr, Xte = tr[cols].fillna(tr[cols].median()), te[cols].fillna(tr[cols].median())
    else:
        Xtr, Xte = tr[cols], te[cols]
    if tr["y"].nunique() < 2:
        return np.full(len(te), tr["y"].mean())
    m = _model(ad)
    if ad == "mitra":
        m.fit(Xtr, tr["y"].to_numpy())
        return m.predict_proba(Xte)[:, 1]
    m.fit(Xtr.to_numpy(float) if ad in BAGLAM_MODELLERI else Xtr, tr["y"].to_numpy())
    return m.predict_proba(Xte.to_numpy(float) if ad in BAGLAM_MODELLERI else Xte)[:, 1]


# ------------------------------------------------------------------ değerlendirme
def _olc(y: np.ndarray, p: np.ndarray, r: np.ndarray) -> dict:
    from sklearn.metrics import log_loss, roc_auc_score

    p = np.clip(p, 1e-4, 1 - 1e-4)
    ust = p >= np.quantile(p, 2 / 3)
    return {"n": int(len(y)), "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else None,
            "logloss": float(log_loss(y, p, labels=[0, 1])), "isabet": float(y.mean()), "isabet_ust": float(y[ust].mean()),
            "r": float(np.nanmean(r)), "r_ust": float(np.nanmean(r[ust]))}


def degerlendir(tf: str, gorevler: str = "ABCD", modeller=("taban", "lojistik", "lightgbm", "tabicl", "tabdpt", "mitra"),
                veri_=None) -> dict:
    d = veri_ or veri_seti(tf)
    sonuc: dict = {}
    for g in gorevler:
        if g not in d:
            continue
        x = d[g].dropna(subset=["y"])
        sonuc[g] = {"satir": int(len(x)), "yillar": {}, "modeller": {}}
        tahminler = {m: [] for m in modeller}
        yy, rr, yil_et = [], [], []
        for Y in TEST_YILLARI[tf]:
            bas, bit = pd.Timestamp(f"{Y}-01-01", tz="UTC"), pd.Timestamp(f"{Y + 1}-01-01", tz="UTC")
            # Eğitim olayının SONUCU test başlamadan bilinmeli: etiket ufku kadar boşluk bırak (sızıntı önleme)
            bosluk = pd.Timedelta(milliseconds=veri.ARALIK_MS[tf] * (F.UFUK if g in "AD" else (YON_H[tf] if g == "B" else 30 // 1)))
            if g == "C":
                bosluk = pd.Timedelta(days=30)
            tr = x[x.index < bas - bosluk]
            te = x[(x.index >= bas) & (x.index < bit)]
            if len(tr) < 300 or len(te) < 100 or tr["y"].nunique() < 2:
                continue
            if len(te) > TEST_EN_COK:
                te = te.sample(TEST_EN_COK, random_state=Y).sort_index()
            yy.append(te["y"].to_numpy())
            rr.append(te["r"].to_numpy(float))
            yil_et.append(np.full(len(te), Y))
            for m in modeller:
                t0 = time.time()
                try:
                    tahminler[m].append(tahmin(m, tr, te, g))
                except Exception as e:  # tek model hatası diğerlerini durdurmaz
                    log.warning("%s %s %s %d: %s", tf, g, m, Y, e)
                    tahminler[m].append(np.full(len(te), np.nan))
                log.info("%s %s %s %d: %d eğitim, %d test, %.1fs", tf, g, m, Y, len(tr), len(te), time.time() - t0)
        if not yy:
            continue
        y, r, yil = np.concatenate(yy), np.concatenate(rr), np.concatenate(yil_et)
        for m in modeller:
            p = np.concatenate(tahminler[m])
            if np.isnan(p).any():
                continue
            genel = _olc(y, p, r)
            yillik = {int(Y): _olc(y[yil == Y], p[yil == Y], r[yil == Y]) for Y in np.unique(yil)}
            hold = (yil >= 2025)
            sonuc[g]["modeller"][m] = {"genel": genel, "yillik": yillik, "holdout": _olc(y[hold], p[hold], r[hold]) if hold.sum() > 50 else None}
        _kabul(sonuc[g], g)
    return sonuc


def _kabul(s: dict, g: str) -> None:
    """DENEYLER.md §9 kabul kuralı."""
    tb = s["modeller"].get("taban")
    if not tb:
        return
    en_iyi, en_auc = None, -1
    for m, v in s["modeller"].items():
        if m == "taban":
            continue
        ge, ho = v["genel"], v["holdout"]
        yillar = list(v["yillik"].values())
        k = {
            "a_auc": (ge["auc"] or 0) >= 0.55 and (ge["auc"] or 0) >= (tb["genel"]["auc"] or 0.5) + 0.02,
            "b_logloss": ge["logloss"] < tb["genel"]["logloss"],
            "c_ust_ucte_bir": sum(x["isabet_ust"] > x["isabet"] for x in yillar) >= math.ceil(0.75 * len(yillar)),
            "d_r": (ge["r_ust"] > 0 and ge["r_ust"] > ge["r"]) if g in "AD" else True,
            "e_holdout": bool(ho) and (ho["auc"] or 0) >= 0.55 and (ho["auc"] or 0) >= ((tb["holdout"] or {}).get("auc") or 0.5) + 0.02,
        }
        k["hepsi"] = all(k.values())
        v["kriter"] = k
        if k["hepsi"] and (ge["auc"] or 0) > en_auc:
            en_iyi, en_auc = m, ge["auc"]
    s["secilen"] = en_iyi


def uret(tfler=("1w", "3d", "1d", "4h"), modeller=("taban", "lojistik", "lightgbm", "tabicl", "tabdpt", "mitra")) -> dict:
    yol = KOK / "raporlar" / "meta.json"
    rapor = json.loads(yol.read_text()) if yol.exists() else {}
    for tf in tfler:
        t0 = time.time()
        rapor[tf] = degerlendir(tf, modeller=modeller)
        rapor[tf]["_sure_sn"] = round(time.time() - t0)
        yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
        log.info("meta %s bitti %.0fs", tf, time.time() - t0)
    return rapor


# ------------------------------------------------------------------ telefon için öğrenci model
def agac_json(model, sutunlar_: list[str]) -> dict:
    """LightGBM modelini JS değerlendiricinin (depo kökündeki meta.js agacTahmin) okuyacağı biçime çevirir."""
    d = model.booster_.dump_model()
    return {"sutunlar": list(sutunlar_), "bicim": 2, "agaclar": [_kompakt(t["tree_structure"]) for t in d["tree_info"]]}


def _kompakt(dg: dict):
    """Yaprak = sayı; iç düğüm = [özellik, eşik, varsayılan_sol(0/1), eksik_tür(0 yok, 1 NaN, 2 sıfır), sol, sağ]."""
    if "split_index" not in dg:
        return float(f"{dg['leaf_value']:.9g}")
    if dg.get("decision_type", "<=") != "<=":
        raise ValueError("yalnız sayısal (<=) bölmeler desteklenir")
    mt = {"None": 0, "NaN": 1, "Zero": 2}[dg.get("missing_type", "None")]
    return [dg["split_feature"], float(dg["threshold"]), int(bool(dg.get("default_left"))), mt,
            _kompakt(dg["left_child"]), _kompakt(dg["right_child"])]


GOREV_AD = {"A": "Sinyal kalite skoru", "B": "Yön (sonraki dönem yükselir mi)", "C": "Hacim durumu sonrası 30 gün",
            "D": "Seviye kırılımı tutar mı"}


def _satir_anahtari(t: pd.DataFrame) -> pd.Series:
    """Olayı tekil tanımlar: zaman + coin + (varsa) sinyal türü, yön, hacim sınıfı."""
    k = pd.Series(t.index.astype(str), index=t.index) + "|" + t["sembol"]
    for c in ("sinyal", "yon", "sinif"):
        if c in t:
            k = k + "|" + t[c].astype(str)
    return pd.Series(k.to_numpy(), index=range(len(t)))


def ogrenci_uret(rapor: dict | None = None, veri_cache: dict | None = None) -> dict:
    """DENEYLER.md §9: her zaman dilimi × görev için öğretmen = kabul edilen model (yoksa AUC'si en yüksek model,
    'deneysel'). Öğretmen 2026-10'a kadarki son bağlamla eğitilir; skorları LightGBM öğrenciye damıtılır (logit
    regresyonu). Öğrencinin öğretmenle korelasyonu ≥ 0.9 değilse telefonda yalnız taban gösterilir.
    Çıktı: <depo kökü>/meta_model.json (telefon ve pano ortak)."""
    import lightgbm as lgb

    rapor = rapor or json.loads((KOK / "raporlar" / "meta.json").read_text())
    out = {"olusturma": time.strftime("%Y-%m-%d", time.gmtime()), "kaynak": "DENEYLER.md §9", "tf": {}}
    for tf, gorevler in rapor.items():
        d = (veri_cache or {}).get(tf) or veri_seti(tf)
        out["tf"][tf] = {}
        for g, s in gorevler.items():
            if g.startswith("_") or not s.get("modeller"):
                continue
            secilen = s.get("secilen")
            adaylar = {m: v for m, v in s["modeller"].items() if m != "taban"}
            ogretmen = secilen or max(adaylar, key=lambda m: adaylar[m]["genel"]["auc"] or 0)
            durum = "dogrulanmis" if secilen else "deneysel"
            x = d[g].dropna(subset=["y"])
            cols = sutunlar(g)
            # Öğrenci verisi: son 3 yılın olaylarından en çok 6 000 (öğretmen bunları bağlamdan önceki veriyle değil,
            # tüm geçmişle skorlar; amaç taklit, doğruluk ölçümü raporda yapıldı)
            hedef = x[x.index >= x.index.max() - pd.Timedelta(days=3 * 365)]
            hedef = hedef.sample(min(6000, len(hedef)), random_state=0).sort_index()
            if ogretmen == "lightgbm":   # öğretmen zaten ağaç modeli: damıtmaya gerek yok, kendisi telefona gider
                ogr = _model("lightgbm").fit(x[cols], x["y"].to_numpy())
                p = ogr.predict_proba(hedef[cols])[:, 1]
                kor = 1.0
            else:
                # Çapraz skorlama: her olay, kendisini İÇERMEYEN bağlamla skorlanır (bağlamdaki satırı "ezberden"
                # yanıtlamasın; öğrenci öğretmenin genelleme davranışını öğrensin).
                kat = np.arange(len(hedef)) % 5
                x_anahtar, h_anahtar = _satir_anahtari(x), _satir_anahtari(hedef)
                p = np.empty(len(hedef))
                for k in range(5):
                    disari = x[~x_anahtar.isin(h_anahtar[kat == k]).to_numpy()]
                    egitim = disari.iloc[-BAGLAM:] if ogretmen in BAGLAM_MODELLERI else disari
                    p[kat == k] = tahmin(ogretmen, egitim, hedef[kat == k], g)
                p = np.clip(p, 1e-3, 1 - 1e-3)
                logit = np.log(p / (1 - p))
                yarim = len(hedef) // 2
                ogr = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=20,
                                        verbose=-1).fit(hedef[cols].iloc[:yarim], logit[:yarim])
                kor = float(np.corrcoef(1 / (1 + np.exp(-ogr.predict(hedef[cols].iloc[yarim:]))), p[yarim:])[0, 1])
                ogr.fit(hedef[cols], logit)
            m = s["modeller"][ogretmen]
            out["tf"][tf][g] = {
                "gorev": GOREV_AD[g], "durum": durum, "ogretmen": ogretmen, "ogrenci_korelasyon": round(kor, 3),
                "telefonda": kor >= 0.9, "auc": m["genel"]["auc"], "taban_auc": s["modeller"]["taban"]["genel"]["auc"],
                "holdout_auc": (m["holdout"] or {}).get("auc"), "isabet": m["genel"]["isabet"], "isabet_ust": m["genel"]["isabet_ust"],
                "esik_ust": float(np.quantile(p, 2 / 3)), "n_test": m["genel"]["n"],
                "model": agac_json(ogr, cols) if kor >= 0.9 else None}
            log.info("öğrenci %s %s: öğretmen %s (%s), korelasyon %.3f", tf, g, ogretmen, durum, kor)
    (MOBIL / "meta_model.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return out



def uret_kaos(tfler=("1w", "3d", "1d", "4h"), modeller=("taban", "lojistik", "lightgbm", "tabicl", "tabdpt", "mitra")) -> dict:
    """DENEYLER.md §10 deney 1 (kaos özellikleriyle aynı çalışma) ve deney 2 (Hurst rejim tablosu). Çıktı: raporlar/meta_kaos.json"""
    global KAOS
    yol = KOK / "raporlar" / "meta_kaos.json"
    rapor = json.loads(yol.read_text()) if yol.exists() else {}
    for tf in tfler:
        t0 = time.time()
        d = veri_seti(tf)
        # Deney 2: Hurst üçte birlerine göre isabet (A, D), 2021-01 → 2026-10
        rejim = {}
        for g in ("A", "D"):
            if g not in d:
                continue
            x = d[g][(d[g].index >= pd.Timestamp("2021-01-01", tz="UTC"))].dropna(subset=["hurst"])
            if len(x) < 300:
                continue
            q = x["hurst"].quantile([1 / 3, 2 / 3]).to_numpy()
            dilim = np.where(x["hurst"] <= q[0], "dusuk", np.where(x["hurst"] <= q[1], "orta", "yuksek"))
            rejim[g] = {"esikler": [float(q[0]), float(q[1])], "genel": float(x["y"].mean()), "n": int(len(x)),
                        "dilimler": {k: {"isabet": float(x["y"][dilim == k].mean()), "n": int((dilim == k).sum()),
                                         "hurst_ort": float(x["hurst"][dilim == k].mean())} for k in ("dusuk", "orta", "yuksek")}}
        KAOS = True
        try:
            rapor[tf] = degerlendir(tf, modeller=modeller, veri_=d)
        finally:
            KAOS = False
        rapor[tf]["_rejim"] = rejim
        rapor[tf]["_sure_sn"] = round(time.time() - t0)
        yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
        log.info("kaos %s bitti %.0fs", tf, time.time() - t0)
    return rapor
