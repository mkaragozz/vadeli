"""Türev konumlanma filtresi deneyi (DENEYLER.md §1, ön kayıtlı). Çıktı: raporlar/turev.json, raporlar/ozet_turev.md"""
from __future__ import annotations

import logging
from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from . import dogrulama as D
from . import turev
from .rapor_uret import UZUN_SET, _fmt, varyantlar
from .strateji import MaliyetParam, RiskParam

log = logging.getLogger(__name__)
BASLANGIC = pd.Timestamp("2022-01-01", tz="UTC")
DILIMLER = D.yillik_dilimler(2022, 2026)
HOLDOUT = ("2025-01-01", "2026-11-01")
FILTRELER = {"+oi": {"oi_teyit": True}, "+fon": {"fonlama_esik": 0.0005}, "+kalabalik": {"kalabalik_z": 1.5},
             "+taker": {"taker_teyit": True},
             "+kombine": {"oi_teyit": True, "fonlama_esik": 0.0005, "kalabalik_z": 1.5}}
ESIKLER = {"+oi": [{"oi_teyit": True, "oi_n": n} for n in (3, 6, 12)],
           "+fon": [{"fonlama_esik": e} for e in (0.0003, 0.0005, 0.001)],
           "+kalabalik": [{"kalabalik_z": z} for z in (1.0, 1.5, 2.0)]}


def _degerlendir(d, p, r, m, ex) -> dict:
    s = D.toplu_calistir(d, p, r, m, ex=ex)
    isl = D.havuz_islemler(s)
    dil = D.dilim_tablosu(s, d, p, r, m, DILIMLER)
    hold = D.r_ozet(isl[isl["giris_zaman"] >= pd.Timestamp(HOLDOUT[0], tz="UTC")]) if len(isl) else D.r_ozet(isl)
    tablo = D.sembol_tablosu(s)
    return {"param": asdict(p), "ozet_metin": p.ozet(), "surum": p.surum, "r": D.r_ozet(isl), "holdout": hold,
            "portfoy": D.egri_metrik(D.portfoy_egrisi(s)), "dilimler": dil.to_dict("records"),
            "karli_sembol_orani": float((tablo["toplam_getiri"] > 0).mean()) if len(tablo) else 0.0}


def uret(r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam()) -> dict:
    d = D.veri_seti(UZUN_SET)
    metrik = {s: turev.arsivden_metrik(s) for s in UZUN_SET}
    vs = varyantlar()
    rapor: dict = {"donem": [str(BASLANGIC.date()), "2026-10-31"], "holdout": HOLDOUT, "tabanlar": {}}
    with D.havuz(d, metrik=metrik, baslangic=BASLANGIC) as ex:
        for taban_ad in ("4s_tetik_btc", "temel"):
            taban = vs[taban_ad]
            t = _degerlendir(d, taban, r, m, ex)
            sonuc = {"taban": t, "filtreler": {}}
            for fad, kw in FILTRELER.items():
                v = _degerlendir(d, replace(taban, **kw), r, m, ex)
                esik_sonuc = []
                for ekw in ESIKLER.get(fad, []):
                    e = _degerlendir(d, replace(taban, **ekw), r, m, ex)
                    esik_sonuc.append({"param": ekw, "ort_r": e["r"]["ort_r"], "islem": e["r"]["islem"]})
                yil_iyi = sum(1 for a, b in zip(v["dilimler"], t["dilimler"]) if (a["r_ort_r"] or 0) > (b["r_ort_r"] or 0))
                k = {
                    "a_ortR_daha_yuksek": v["r"]["ort_r"] > t["r"]["ort_r"],
                    "b_4/5_yil_daha_iyi": yil_iyi >= 4,
                    "c_holdout_daha_iyi": v["holdout"]["ort_r"] > t["holdout"]["ort_r"],
                    "d_esiklerin_2/3_iyi": (sum(x["ort_r"] > t["r"]["ort_r"] for x in esik_sonuc) >= 2) if esik_sonuc else None,
                    "e_islem_>=%40": v["r"]["islem"] >= 0.4 * t["r"]["islem"],
                }
                k["hepsi"] = all(x for x in k.values() if x is not None)
                v.update(esikler=esik_sonuc, yil_iyi=yil_iyi, kriter=k)
                sonuc["filtreler"][fad] = v
                log.info("%s %s: ortR %.3f (taban %.3f) kabul=%s", taban_ad, fad, v["r"]["ort_r"], t["r"]["ort_r"], k["hepsi"])
            rapor["tabanlar"][taban_ad] = sonuc
    D.kaydet("turev.json", rapor)
    (D.RAPOR_DIZINI / "ozet_turev.md").write_text(markdown(rapor))
    return rapor


def markdown(rp: dict) -> str:
    L = [f"_Dönem {rp['donem'][0]} → {rp['donem'][1]}, holdout {rp['holdout'][0]} → 2026-10. Maliyetler dahil._\n"]
    for tad, x in rp["tabanlar"].items():
        t = x["taban"]
        L.append(f"### Taban: {tad} (`{t['ozet_metin']}`)\n")
        L.append("| Varyant | İşlem | Ort. R | t | PF(R) | Kazanma | Portföy | Max DD | Kârlı sembol | Holdout R | Daha iyi yıl | Eşikler (ort. R) | Kabul |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        def satir(ad, v, taban=False):
            k = v.get("kriter", {})
            esik = ", ".join(f"{_fmt(e['ort_r'], n=3)}" for e in v.get("esikler", [])) or "-"
            kabul = "-" if taban else ("✓ " if k.get("hepsi") else "✗ ") + "".join(
                (kk[0] if vv else kk[0].upper() + "̶") for kk, vv in k.items() if kk != "hepsi" and vv is not None)
            L.append(f"| {ad} | {v['r']['islem']} | {_fmt(v['r']['ort_r'], n=3)} | {_fmt(v['r']['t'], n=1)} | {_fmt(v['r']['pf_r'])} | "
                     f"{_fmt(v['r']['kazanma'], True)} | {_fmt(v['portfoy'].get('toplam_getiri'), True)} | {_fmt(v['portfoy'].get('max_dusus'), True)} | "
                     f"{_fmt(v['karli_sembol_orani'], True)} | {_fmt(v['holdout']['ort_r'], n=3)} | {'-' if taban else str(v['yil_iyi']) + '/5'} | {esik} | {kabul} |")
        satir("taban", t, True)
        for fad, v in x["filtreler"].items():
            satir(fad, v)
        L.append("\nYıllık ort. R: " + " · ".join(
            f"{ad}: " + "/".join(_fmt(dl['r_ort_r'], n=3) for dl in v["dilimler"])
            for ad, v in [("taban", t)] + list(x["filtreler"].items())) + "\n")
    L.append("Kabul sütunu: a=ort. R daha yüksek, b=≥4/5 yıl daha iyi, c=holdout daha iyi, d=≥2/3 eşik daha iyi, "
             "e=işlem ≥ tabanın %40'ı; büyük harf ve üstü çizili = sağlanmadı.")
    return "\n".join(L) + "\n"
