"""Piyasa taraması ölçüleri (depo kökündeki tarama.js ile BİREBİR aynı tanımlar) ve hacim durumu geçmiş istatistiği.

Soru: "Hacmi patlayan / artan / kuruyan coinler sonraki 7, 30, 90 günde ne yaptı?"
Yöntem: Binance spot arşivi (hacimce ilk 200 USDT çifti, 1s mumdan günlük), 2021-01 → 2026-10. Her gün, o güne kadar
KAPANMIŞ veriyle ölçüler hesaplanır (look-ahead yok); sınıfa giren her (coin, gün) bir olaydır. Sonraki getiri o günün
kapanışından ölçülür ve AYNI GÜNLERDEKİ tüm coinlerin getirisiyle karşılaştırılır (piyasa geneli etkisini ayırmak için).
Uyarı: aynı gün çok sayıda coin aynı sınıfa girer (ör. piyasa geneli hacim patlaması); olaylar bağımsız değildir.
Bu yüzden "farklı gün" sayısı da raporlanır.

Çıktı: <depo kökü>/tarama_istatistik.json (telefon ve bilgisayar panosu bunu okur), raporlar/ozet_tarama.md
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import veri

log = logging.getLogger(__name__)
KOK = Path(__file__).resolve().parent.parent
SPOT_ONBELLEK = veri.VARSAYILAN_ONBELLEK / "spot"
ISTAT_YOLU = KOK.parent / "tarama_istatistik.json"  # telefon uygulaması depo kökünde
UFUKLAR = (7, 30, 90)
BASLANGIC = "2021-01-01"
ESIK_ADAYLARI = {"patlama": (2.0, 3.0, 5.0), "artan": (1.3, 1.5, 2.0), "kuruma": (0.3, 0.4, 0.5)}
VARSAYILAN_ESIK = {"patlama": 3.0, "artan": 1.5, "kuruma": 0.4}
KRIPTO_B = {"BNB", "ARB", "SHIB", "TRB", "CKB", "BEB", "BB", "YB", "DGB", "WEB", "LAB", "SUB", "PUB", "CRB"}
EMTIA = {"XAUT", "PAXG", "XAU", "XAG"}


def varlik_turu(baz: str, kapanislar: np.ndarray) -> str:
    if baz in EMTIA:
        return "emtia"
    if baz.endswith("B") and len(baz) >= 3 and baz not in KRIPTO_B:
        return "hisse"
    son = kapanislar[-90:]
    if len(son) >= 30 and ((son > 0.97) & (son < 1.03)).all():
        return "stabil"
    return "kripto"


def olcu_serileri(g: pd.DataFrame) -> pd.DataFrame:
    """Günlük mumlardan (index = gün açılışı, yalnız kapanmış günler) her gün için tarama.js `olculer` değerleri.
    Satır t = t gününün kapanışında bilinen değerler."""
    c, qv = g["close"], g["quote_volume"]
    out = pd.DataFrame(index=g.index)
    for n in (7, 30, 90, 180, 365):
        out[f"g{n}"] = c / c.shift(n) - 1
    h7 = qv.rolling(7).mean()
    h20 = qv.shift(1).rolling(20).mean()          # qv.slice(-21, -1): son gün hariç önceki 20
    h30 = qv.rolling(30).mean()
    h90 = qv.rolling(90).mean()
    out["hacim30"] = h30
    out["hacim_egilim"] = h7 / h30
    out["hacim_patlama"] = qv / h20
    out["hacim_kuruma"] = h7 / h90
    out["zirveden"] = c / c.rolling(365, min_periods=1).max() - 1
    out["gun"] = np.arange(1, len(g) + 1)
    return out


def siniflar(o: pd.DataFrame, e: dict) -> pd.DataFrame:
    """tarama.js hacimSiniflari ile aynı."""
    p = o["hacim_patlama"] >= e["patlama"]
    return pd.DataFrame({"patlama": p, "artan": (o["hacim_egilim"] >= e["artan"]) & ~p,
                         "kuruma": o["hacim_kuruma"] <= e["kuruma"]}, index=o.index)


def gunluk_set(semboller: list[str] | None = None) -> dict[str, pd.DataFrame]:
    d = {}
    for yol in sorted(SPOT_ONBELLEK.glob("*_1h.csv")):
        s = yol.name.split("_")[0]
        if semboller and s not in semboller:
            continue
        g = veri.yeniden_ornekle(veri._csv_oku(yol), "1d")
        g = g[g.index < pd.Timestamp("2026-11-01", tz="UTC")]
        if len(g) < 120 or varlik_turu(s[:-4], g["close"].to_numpy()) != "kripto":
            continue
        d[s] = g
    return d


def panel(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(gün, sembol) satırlı panel: ölçüler + sonraki getiriler (yalnız çıktı/etiket; ölçülere girmez)."""
    parcalar = []
    for s, g in d.items():
        o = olcu_serileri(g)
        c = g["close"]
        for h in UFUKLAR:
            o[f"ileri{h}"] = c.shift(-h) / c - 1
        o["sembol"] = s
        parcalar.append(o[o["gun"] >= 90])  # ısınma: 90 günlük hacim ortalaması gerekli
    p = pd.concat(parcalar)
    return p[p.index >= pd.Timestamp(BASLANGIC, tz="UTC")]


def sinif_istatistik(p: pd.DataFrame, maske: pd.Series) -> dict:
    out = {"olay": int(maske.sum()), "farkli_gun": int(p.index[maske].nunique())}
    for h in UFUKLAR:
        k = f"ileri{h}"
        x = p.loc[maske, k].dropna()
        tum = p[k].dropna()
        # aynı günlerdeki tüm coinler (piyasa karşılaştırması)
        gunler = p.index[maske].unique()
        ayni = p.loc[p.index.isin(gunler), k].dropna()
        if len(x) < 30:
            out[f"g{h}"] = None
            continue
        out[f"g{h}"] = {
            "n": int(len(x)), "yukselme_olasiligi": float((x > 0).mean()), "medyan": float(x.median()),
            "ortalama": float(x.mean()), "dusme_10_olasiligi": float((x < -0.10).mean()),
            "yukselme_10_olasiligi": float((x > 0.10).mean()),
            "piyasa_yukselme_olasiligi": float((ayni > 0).mean()), "piyasa_medyan": float(ayni.median()),
            "genel_yukselme_olasiligi": float((tum > 0).mean()), "genel_medyan": float(tum.median()),
            "fark_medyan": float(x.median() - ayni.median()),
        }
    return out


def uret() -> dict:
    t0 = time.time()
    d = gunluk_set()
    p = panel(d)
    log.info("tarama istatistiği: %d coin, %d satır", len(d), len(p))
    tarama: dict = {}
    for ad, adaylar in ESIK_ADAYLARI.items():
        tarama[ad] = []
        for e in adaylar:
            es = dict(VARSAYILAN_ESIK, **{ad: e})
            m = siniflar(p, es)[ad]
            tarama[ad].append({"esik": e, **sinif_istatistik(p, m)})
    # Eşik seçimi (önceden yazılan kural): en az 300 olay ve 100 farklı gün içinde, 30 günlük medyan getirinin aynı
    # günlerdeki tüm coinlerden farkı mutlak değerce en büyük olan. Fark yoksa varsayılan kalır.
    esikler = dict(VARSAYILAN_ESIK)
    for ad, sat in tarama.items():
        uygun = [x for x in sat if x["olay"] >= 300 and x["farkli_gun"] >= 100 and x.get("g30")]
        if uygun:
            esikler[ad] = max(uygun, key=lambda x: abs(x["g30"]["fark_medyan"]))["esik"]
    secili = siniflar(p, esikler)
    sonuc = {
        "olusturma": time.strftime("%Y-%m-%d", time.gmtime()), "kaynak": "Binance spot arşivi (data.binance.vision)",
        "donem": f"{BASLANGIC[:7]} → 2026-10", "sembol": len(d), "esikler": esikler, "esik_taramasi": tarama,
        "siniflar": {ad: {**sinif_istatistik(p, secili[ad]), "donem": f"{BASLANGIC[:7]} → 2026-10", "sembol": len(d)}
                     for ad in ("patlama", "artan", "kuruma")},
        "genel": {f"g{h}": {"yukselme_olasiligi": float((p[f'ileri{h}'].dropna() > 0).mean()),
                            "medyan": float(p[f"ileri{h}"].dropna().median())} for h in UFUKLAR},
    }
    ISTAT_YOLU.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    (KOK / "raporlar" / "ozet_tarama.md").write_text(markdown(sonuc))
    log.info("tarama istatistiği bitti %.0fs", time.time() - t0)
    return sonuc


def markdown(r: dict) -> str:
    y = lambda x: "-" if x is None else f"{x * 100:+.1f}%"
    o = lambda x: "-" if x is None else f"{x * 100:.0f}%"
    L = [f"_Kaynak: {r['kaynak']}, {r['sembol']} kripto (hacimce ilk 200 spot USDT çiftinden), {r['donem']}._\n",
         "| Durum | Eşik | Olay | Farklı gün | 7g yükselme | 7g medyan | 30g yükselme | 30g medyan (aynı günler tüm coinler) | 90g yükselme | 90g medyan |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for ad, sat in r["esik_taramasi"].items():
        for x in sat:
            g7, g30, g90 = x.get("g7") or {}, x.get("g30") or {}, x.get("g90") or {}
            sec = " ←" if r["esikler"][ad] == x["esik"] else ""
            L.append(f"| {ad}{sec} | {x['esik']} | {x['olay']} | {x['farkli_gun']} | {o(g7.get('yukselme_olasiligi'))} | "
                     f"{y(g7.get('medyan'))} | {o(g30.get('yukselme_olasiligi'))} | {y(g30.get('medyan'))} ({y(g30.get('piyasa_medyan'))}) | "
                     f"{o(g90.get('yukselme_olasiligi'))} | {y(g90.get('medyan'))} |")
    g = r["genel"]
    L.append(f"\nTüm coin-günler: 7g yükselme {o(g['g7']['yukselme_olasiligi'])}, 30g {o(g['g30']['yukselme_olasiligi'])}, "
             f"90g {o(g['g90']['yukselme_olasiligi'])}.")
    return "\n".join(L) + "\n"
