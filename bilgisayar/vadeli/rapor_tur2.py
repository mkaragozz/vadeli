"""Geliştirme turu 2 (DENEYLER.md §2, ön kayıtlı). Çıktı: raporlar/tur2.json, raporlar/ozet_tur2.md

  * Kenar varyantları: +rs (göreli güç), +basabas (başabaş stop), 1g_tetik (günlük tetik) — taban: canlı varsayılan
  * K1: hayatta kalma yanlılığı (2022-01'in hacimce ilk 60'ı, sonradan listeden çıkanlar dahil)
  * K2: tek hesap portföy simülasyonu, toplam açık risk tavanı
"""
from __future__ import annotations

import logging
from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from . import dogrulama as D
from . import turev
from .rapor_turev import BASLANGIC, HOLDOUT, _degerlendir
from .rapor_uret import UZUN_SET, _fmt, varyantlar
from .strateji import MaliyetParam, RiskParam, StratejiParam

log = logging.getLogger(__name__)

# 2022-01 arşiv hacim sırasına göre ilk 60 (o anda bilinebilecek evren). İlk 5'i bugün listede yok.
CIKMIS_2022 = ["LUNAUSDT", "MATICUSDT", "EOSUSDT", "SXPUSDT", "ANTUSDT"]
EVREN_2022 = ['BTCUSDT', 'ETHUSDT', 'FTMUSDT', 'LUNAUSDT', 'ATOMUSDT', 'NEARUSDT', 'ADAUSDT', 'SOLUSDT', 'LINKUSDT',
              'SANDUSDT', 'MATICUSDT', 'DOGEUSDT', 'DOTUSDT', 'BNBUSDT', '1000SHIBUSDT', 'AVAXUSDT', 'MANAUSDT',
              'GALAUSDT', 'ONEUSDT', 'XRPUSDT', 'ICPUSDT', 'CRVUSDT', 'SUSHIUSDT', 'PEOPLEUSDT', 'LTCUSDT', 'LRCUSDT',
              'DYDXUSDT', 'ROSEUSDT', 'AXSUSDT', 'EOSUSDT', 'FILUSDT', 'AAVEUSDT', 'THETAUSDT', 'ALICEUSDT', 'YFIUSDT',
              'CHRUSDT', 'ALGOUSDT', 'XTZUSDT', 'CELRUSDT', 'ETCUSDT', 'UNIUSDT', 'VETUSDT', 'ENJUSDT', 'KAVAUSDT',
              'SXPUSDT', 'BCHUSDT', 'ANTUSDT', 'XLMUSDT', 'EGLDUSDT', 'COTIUSDT', 'KNCUSDT', 'TRXUSDT', 'DUSKUSDT',
              'ZECUSDT', 'GTCUSDT', 'RUNEUSDT', 'TLMUSDT', '1INCHUSDT', 'RVNUSDT', 'ARUSDT']
TAVANLAR = {"yok": None, "8R": 8, "5R": 5, "3R": 3}


def taban() -> StratejiParam:
    return replace(varyantlar()["4s_tetik_btc"], oi_teyit=True)


def adaylar(t: StratejiParam) -> dict:
    """Ön kayıtlı varyantlar ve eşik taramaları (DENEYLER.md §2)."""
    gun = replace(t, tetik_tf="1d", rejim_tf="1d")
    return {
        "+rs": (replace(t, rs_n=42), [replace(t, rs_n=n) for n in (21, 42, 84)]),
        "+basabas": (replace(t, basabas_r=1.0), [replace(t, basabas_r=x) for x in (1.0, 1.5, 2.0)]),
        "1g_tetik": (gun, [replace(gun, giris_n=n) for n in (10, 20, 40)]),
    }


# ------------------------------------------------------------------ K2: tek hesap portföy
def tek_hesap(isl: pd.DataFrame, risk: float = 0.01, tavan_r: float | None = None, hesap: float = 1000.0) -> dict:
    """Tüm sembollerin işlemleri tek ortak özkaynakla. Girişte risk = özkaynak × risk; kâr/zarar = R × o risk.
    Toplam açık risk (açık pozisyon sayısı × 1R) tavanı doluysa yeni sinyal atlanır.
    Yaklaşımlar: (1) atlanan işlem o sembolün sonraki sinyallerini değiştirmez (alt hesap motorundaki sıralama korunur);
    (2) özkaynak işlem kapanışlarında güncellenir (açık pozisyonların anlık zararı düşüşe katılmaz → max düşüş
    olduğundan biraz iyimser)."""
    if isl.empty:
        return {}
    olay = []
    for k, x in enumerate(isl.itertuples(index=False)):
        olay.append((x.giris_zaman, 1, k))
        olay.append((x.cikis_zaman, 0, k))
    olay.sort(key=lambda e: (e[0], e[1]))  # aynı anda önce çıkışlar
    r = isl["r"].to_numpy(float)
    ozk = hesap
    acik: dict[int, float] = {}
    atlanan = 0
    egri = []
    for zaman, tur, k in olay:
        if tur == 1:
            if tavan_r is not None and len(acik) + 1 > tavan_r:
                atlanan += 1
                continue
            acik[k] = ozk * risk
        elif k in acik:
            ozk += r[k] * acik.pop(k)
            egri.append((zaman, ozk))
    e = pd.Series([v for _, v in egri], index=pd.DatetimeIndex([z for z, _ in egri])).groupby(level=0).last()
    e = e.resample("1D").last().ffill()
    e = pd.concat([pd.Series([hesap], index=[e.index[0] - pd.Timedelta(days=1)]), e])
    m = D.egri_metrik(e)
    alinan = len(isl) - atlanan
    eszaman = _eszamanli(isl)
    return {**m, "getiri_dd": (m["yillik_getiri"] / -m["max_dusus"]) if m.get("max_dusus") else None,
            "islem": int(alinan), "atlanan": int(atlanan), "max_eszamanli": int(eszaman.max()),
            "ort_eszamanli": float(eszaman.mean()),
            "yillik": {str(y): float(g.iloc[-1] / g.iloc[0] - 1) for y, g in e.groupby(e.index.year) if len(g) > 2}}


def tek_hesap_dagilim(isl: pd.DataFrame, risk: float = 0.01, tavan_r: float | None = None, hesap: float = 1000.0,
                     n: int = 20) -> dict:
    """Aynı saatte açılan sinyallerin hangisinin tavana takılacağı keyfidir (işlemlerin %65'i başka bir işlemle aynı
    anda açılıyor). Bu yüzden işlem sırası n kez rastgele karıştırılır; medyan ve aralık raporlanır."""
    if isl.empty:
        return {}
    ornek = [tek_hesap(isl.sample(frac=1, random_state=k).reset_index(drop=True), risk, tavan_r, hesap) for k in range(n)]
    med = {k: float(np.median([o[k] for o in ornek])) for k in ("toplam_getiri", "yillik_getiri", "max_dusus", "sharpe",
                                                                "islem", "atlanan")}
    med["islem"], med["atlanan"] = int(round(med["islem"])), int(round(med["atlanan"]))
    med["getiri_dd"] = med["yillik_getiri"] / -med["max_dusus"] if med["max_dusus"] else None
    med["yillik_min"] = float(min(o["yillik_getiri"] for o in ornek))
    med["yillik_max"] = float(max(o["yillik_getiri"] for o in ornek))
    med["max_eszamanli"] = ornek[0]["max_eszamanli"]
    med["ort_eszamanli"] = ornek[0]["ort_eszamanli"]
    return med


def _eszamanli(isl: pd.DataFrame) -> pd.Series:
    """Her işlem girişinde açık olan pozisyon sayısı (tavansız)."""
    g = isl["giris_zaman"].to_numpy()
    c = isl["cikis_zaman"].to_numpy()
    return pd.Series([int(((g <= t) & (c > t)).sum()) for t in g])


# ------------------------------------------------------------------ ana akış
def uret(r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam()) -> dict:
    rapor = kenar_ve_portfoy(r, m)
    rapor["hayatta_kalma"] = hayatta_kalma(r, m)
    D.kaydet("tur2.json", rapor)
    (D.RAPOR_DIZINI / "ozet_tur2.md").write_text(markdown(rapor))
    return rapor


def kenar_ve_portfoy(r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam()) -> dict:
    t = taban()
    d = D.veri_seti(UZUN_SET)
    metrik = {s: turev.arsivden_metrik(s) for s in UZUN_SET}
    rapor: dict = {"donem": [str(BASLANGIC.date()), "2026-10-31"], "holdout": HOLDOUT, "taban_surum": t.surum,
                   "taban_ozet": t.ozet()}
    with D.havuz(d, metrik=metrik, baslangic=BASLANGIC) as ex:
        tb = _degerlendir(d, t, r, m, ex)
        taban_isl = D.havuz_islemler(D.toplu_calistir(d, t, r, m, ex=ex))
        rapor["taban"] = tb
        rapor["varyantlar"] = {}
        for ad, (v, esikler) in adaylar(t).items():
            sv = _degerlendir(d, v, r, m, ex)
            es = []
            for e in esikler:
                x = _degerlendir(d, e, r, m, ex)
                es.append({"ozet": e.ozet(), "ort_r": x["r"]["ort_r"], "islem": x["r"]["islem"],
                           "holdout": x["holdout"]["ort_r"]})
            yil_iyi = sum(1 for a, b in zip(sv["dilimler"], tb["dilimler"]) if (a["r_ort_r"] or 0) > (b["r_ort_r"] or 0))
            k = {
                "a_ortR_+0.02_daha_yuksek": sv["r"]["ort_r"] >= tb["r"]["ort_r"] + 0.02,
                "b_4/5_yil_daha_iyi": yil_iyi >= 4,
                "c_holdout_daha_iyi": sv["holdout"]["ort_r"] > tb["holdout"]["ort_r"],
                "d_esiklerin_2/3_iyi": sum(x["ort_r"] > tb["r"]["ort_r"] for x in es) >= 2,
                "e_islem_>=%40": sv["r"]["islem"] >= 0.4 * tb["r"]["islem"],
            }
            k["hepsi"] = all(k.values())
            sv.update(esikler=es, yil_iyi=yil_iyi, kriter=k)
            rapor["varyantlar"][ad] = sv
            log.info("tur2 %s: ortR %.3f (taban %.3f) kabul=%s", ad, sv["r"]["ort_r"], tb["r"]["ort_r"], k["hepsi"])

    # K2: tek hesap
    rapor["tek_hesap"] = {ad: tek_hesap_dagilim(taban_isl, r.risk_yuzde / 100, tv, r.hesap) for ad, tv in TAVANLAR.items()}
    # Ek (ön kayıtta yoktu, yalnız betimleyici): işlem başı risk seviyesine göre, tavansız ve 5R tavanlı
    rapor["risk_tablosu"] = [{"risk": rk, "tavan": ad, **tek_hesap_dagilim(taban_isl, rk / 100, tv, r.hesap)}
                             for rk in (0.25, 0.5, 1.0) for ad, tv in (("yok", None), ("5R", 5))]
    gecerli = {a: x for a, x in rapor["tek_hesap"].items() if x.get("getiri_dd") is not None}
    secilen = max(gecerli, key=lambda a: (round(gecerli[a]["getiri_dd"], 2), gecerli[a]["max_dusus"])) if gecerli else None
    rapor["tek_hesap_secilen"] = secilen
    rapor["alt_hesap_portfoy"] = tb["portfoy"]
    return rapor


def hayatta_kalma(r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam()) -> dict:
    """K1: 2022-01'de bilinebilecek evren (hacimce ilk 60), sonradan listeden çıkanlar dahil."""
    t = taban()
    d2 = D.veri_seti(EVREN_2022)
    d2 = {s: v for s, v in d2.items() if len(v[0])}
    metrik2 = {s: turev.arsivden_metrik(s) for s in d2}
    with D.havuz(d2, metrik=metrik2, baslangic=BASLANGIC) as ex:
        s2 = D.toplu_calistir(d2, t, r, m, ex=ex)
    isl2 = D.havuz_islemler(s2)
    tablo2 = D.sembol_tablosu(s2)
    hold = isl2[isl2["giris_zaman"] >= pd.Timestamp(HOLDOUT[0], tz="UTC")]
    cik = isl2[isl2["sembol"].isin(CIKMIS_2022)]
    ana_disi = isl2[~isl2["sembol"].isin(UZUN_SET)]
    return {
        "evren_2022": {"r": D.r_ozet(isl2), "holdout": D.r_ozet(hold), "sembol": int(len(tablo2)),
                       "karli_sembol_orani": float((tablo2["toplam_getiri"] > 0).mean()) if len(tablo2) else 0.0,
                       "dilimler": D.dilim_tablosu(s2, d2, t, r, m, D.yillik_dilimler(2022, 2026)).to_dict("records")},
        "cikmis": {"r": D.r_ozet(cik), "sembol": {s: D.r_ozet(cik[cik["sembol"] == s]) for s in CIKMIS_2022}},
        "ana_set_disi": {"r": D.r_ozet(ana_disi), "holdout": D.r_ozet(ana_disi[ana_disi["giris_zaman"] >= pd.Timestamp(HOLDOUT[0], tz="UTC")])},
    }


def markdown(rp: dict) -> str:
    t = rp["taban"]
    L = [f"_Dönem {rp['donem'][0]} → {rp['donem'][1]}, holdout {rp['holdout'][0]} → 2026-10. Maliyetler dahil. "
         f"Taban: `{rp['taban_ozet']}` ({rp['taban_surum']})._\n",
         "### Kenar varyantları\n",
         "| Varyant | İşlem | Ort. R | t | PF(R) | Holdout R (t) | Daha iyi yıl | Eşikler (ort. R) | Kabul |",
         "|---|---|---|---|---|---|---|---|---|",
         f"| taban | {t['r']['islem']} | {_fmt(t['r']['ort_r'], n=3)} | {_fmt(t['r']['t'], n=1)} | {_fmt(t['r']['pf_r'])} | "
         f"{_fmt(t['holdout']['ort_r'], n=3)} ({_fmt(t['holdout']['t'], n=1)}) | - | - | - |"]
    for ad, v in rp["varyantlar"].items():
        k = v["kriter"]
        kabul = ("✓ " if k["hepsi"] else "✗ ") + " ".join((kk[0] if vv else f"~~{kk[0]}~~") for kk, vv in k.items() if kk != "hepsi")
        L.append(f"| {ad} | {v['r']['islem']} | {_fmt(v['r']['ort_r'], n=3)} | {_fmt(v['r']['t'], n=1)} | {_fmt(v['r']['pf_r'])} | "
                 f"{_fmt(v['holdout']['ort_r'], n=3)} ({_fmt(v['holdout']['t'], n=1)}) | {v['yil_iyi']}/5 | "
                 f"{' / '.join(_fmt(e['ort_r'], n=3) for e in v['esikler'])} | {kabul} |")
    L.append("\nYıllık ort. R: " + " · ".join(
        f"{ad}: " + "/".join(_fmt(dl['r_ort_r'], n=3) for dl in v["dilimler"])
        for ad, v in [("taban", t)] + list(rp["varyantlar"].items())))
    L.append("\nKabul: a = ort. R en az +0.02 yüksek, b = ≥4/5 yıl daha iyi, c = holdout daha iyi, d = ≥2/3 eşik daha iyi, "
             "e = işlem ≥ tabanın %40'ı; üstü çizili = sağlanmadı.\n")
    L.append("### K2 — Tek hesap portföy (22 sembol, ortak özkaynak, %1 risk/işlem)\n")
    L.append("| Açık risk tavanı | İşlem | Atlanan | Toplam | Yıllık | Max DD | Yıllık/DD | Sharpe |")
    L.append("|---|---|---|---|---|---|---|---|")
    for ad, x in rp["tek_hesap"].items():
        if not x:
            continue
        L.append(f"| {ad}{' ←' if ad == rp['tek_hesap_secilen'] else ''} | {x['islem']} | {x['atlanan']} | "
                 f"{_fmt(x['toplam_getiri'], True)} | {_fmt(x['yillik_getiri'], True)} | {_fmt(x['max_dusus'], True)} | "
                 f"{_fmt(x['getiri_dd'])} | {_fmt(x['sharpe'])} |")
    L.append("\nTavanlı satırlar: aynı saatte açılan sinyallerin sırası 20 kez rastgele karıştırıldı, medyan gösteriliyor.\n")
    L.append("| İşlem başı risk | Tavan | Yıllık (medyan) | Yıllık aralığı | Max DD | Yıllık/DD |")
    L.append("|---|---|---|---|---|---|")
    for x in rp.get("risk_tablosu", []):
        L.append(f"| %{x['risk']} | {x['tavan']} | {_fmt(x['yillik_getiri'], True)} | {_fmt(x['yillik_min'], True)} … "
                 f"{_fmt(x['yillik_max'], True)} | {_fmt(x['max_dusus'], True)} | {_fmt(x['getiri_dd'])} |")
    x0 = rp["tek_hesap"].get("yok") or {}
    a = rp["alt_hesap_portfoy"]
    L.append(f"\nAynı anda açık pozisyon (tavansız): en çok {x0.get('max_eszamanli')}, ortalama {_fmt(x0.get('ort_eszamanli'), n=1)}. "
             f"Karşılaştırma — eski model (22 ayrı alt hesap, eşit ağırlık): yıllık {_fmt(a.get('yillik_getiri'), True)}, "
             f"max DD {_fmt(a.get('max_dusus'), True)}.\n")
    h = rp["hayatta_kalma"]
    e = h["evren_2022"]
    L.append("### K1 — Hayatta kalma yanlılığı (2022-01'in hacimce ilk 60'ı)\n")
    L.append(f"* Tüm evren ({e['sembol']} sembol): {e['r']['islem']} işlem, ort. R {_fmt(e['r']['ort_r'], n=3)} "
             f"(t {_fmt(e['r']['t'], n=1)}), holdout {_fmt(e['holdout']['ort_r'], n=3)} (t {_fmt(e['holdout']['t'], n=1)}), "
             f"kârlı sembol {_fmt(e['karli_sembol_orani'], True)}")
    L.append("* Yıllık ort. R: " + " / ".join(_fmt(dl['r_ort_r'], n=3) for dl in e["dilimler"]))
    L.append(f"* Ana set dışında kalanlar: ort. R {_fmt(h['ana_set_disi']['r']['ort_r'], n=3)} ({h['ana_set_disi']['r']['islem']} işlem), "
             f"holdout {_fmt(h['ana_set_disi']['holdout']['ort_r'], n=3)}")
    L.append(f"* Listeden çıkanlar: ort. R {_fmt(h['cikmis']['r']['ort_r'], n=3)} ({h['cikmis']['r']['islem']} işlem) — " +
             ", ".join(f"{s[:-4]} {_fmt(v['ort_r'], n=2)} ({v['islem']})" for s, v in h["cikmis"]["sembol"].items()))
    return "\n".join(L) + "\n"
