"""`python tarayici.py backtest` komutunun yaptığı tam doğrulama ve rapor üretimi.

Çıktılar (raporlar/):
  rapor.json                 panonun Backtest ekranının okuduğu özet (tüm bölümler)
  semboller_<varyant>.csv     sembol bazında sonuçlar
  dilimler_<varyant>.csv      yıllık dilimler
  izgara.csv, walk_forward.csv
  ozet.md                    RAPOR.md'ye konan tablolar (otomatik)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import dogrulama as D
from . import veri
from .strateji import MaliyetParam, RiskParam, StratejiParam

log = logging.getLogger(__name__)

# Uzun geçmişli ana set: zorunlu 5 sembol + hacimce büyük, 2021 öncesinden beri işlem gören kriptolar.
UZUN_SET = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT",
            "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BCHUSDT", "ETCUSDT", "ATOMUSDT", "FILUSDT", "AAVEUSDT", "XLMUSDT",
            "NEARUSDT", "UNIUSDT", "ZECUSDT", "SANDUSDT"]

# Alternatifler: deneme öncesi tanımlandı (DENEYLER.md, "ön kayıt").
def varyantlar() -> dict[str, StratejiParam]:
    t = StratejiParam()
    return {
        "temel": t,
        "4s_tetik": replace(t, tetik_tf="4h", rejim_tf="4h"),
        "genis_cikis": replace(t, cikis_n=20, atr_kat=4.0),
        "hacim_filtre": replace(t, hacim_kat=1.5),
        "vol_filtre": replace(t, vol_min=0.004),
        "btc_rejim": replace(t, btc_filtre=True),
        "sadece_long": replace(t, yon="long"),
        "4s_tetik_btc": replace(t, tetik_tf="4h", rejim_tf="4h", btc_filtre=True),
    }


HOLDOUT = ("2025-01-01", "2026-11-01")
SAGLIK_VARYANTLARI = ("temel", "4s_tetik", "4s_tetik_btc")


def kriterler(v: dict, izg: dict | None, wf: list | None, sag: dict | None) -> dict:
    """DENEYLER.md'deki ön kayıtlı 'canlıya uygun' kuralları."""
    o = v["ozet"]
    hr = o["havuz_r"]
    pozitif_yil = sum(1 for x in v["dilimler"] if (x.get("r_toplam_r") or 0) > 0)
    k = {
        "1_ortR_pozitif_ve_PF>=1.10": hr["ort_r"] > 0 and (hr["pf_r"] or 0) >= 1.10,
        "2_en_az_5/7_yil_pozitif": pozitif_yil >= 5,
        "3_sembollerin_%60_kârlı": (o.get("karli_sembol_orani") or 0) >= 0.60,
        "4_izgara_%60_kombinasyon_pozitif": bool(izg) and izg["ozet"]["karli_kombinasyon_orani_R"] >= 0.60,
        "5_walk_forward": bool(wf) and np.mean([x["test_ort_r"] for x in wf]) > 0 and sum(x["test_ort_r"] > 0 for x in wf) >= 3,
        "6_holdout_pozitif": (v["holdout"].get("r_ort_r") or 0) > 0,
    }
    if sag:
        kar = sag.get("karistirilmis", [])
        k["7_saglik"] = bool(kar) and np.mean([x["ort_r"] for x in kar]) <= 0.02 and sag["rastgele_yuruyus"]["medyan_getiri"] < 0
    else:
        k["7_saglik"] = None
    k["hepsi"] = all(x for x in k.values() if x is not None) and k["7_saglik"] is not None
    return {kk: (bool(vv) if vv is not None else None) for kk, vv in k.items()}


def _fmt(x, yuzde=False, n=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x * 100:.1f}%" if yuzde else f"{x:.{n}f}"


def varyant_degerlendir(ad: str, p: StratejiParam, d: dict, r: RiskParam, m: MaliyetParam, ex) -> dict:
    t0 = time.time()
    sonuc = D.toplu_calistir(d, p, r, m, ex=ex)
    oz = D.genel_ozet(sonuc)
    dil = D.dilim_tablosu(sonuc, d, p, r, m, D.yillik_dilimler())
    hold = D.dilim_tablosu(sonuc, d, p, r, m, [HOLDOUT]).iloc[0].to_dict()
    tablo = D.sembol_tablosu(sonuc)
    e = D.portfoy_egrisi(sonuc)
    D.kaydet(f"semboller_{ad}.csv", tablo)
    D.kaydet(f"dilimler_{ad}.csv", dil)
    log.info("varyant %s: %.1fs ortR=%.3f", ad, time.time() - t0, oz["havuz_r"]["ort_r"])
    return {"param": asdict(p), "ozet_metin": p.ozet(), "surum": p.surum, "ozet": oz, "dilimler": dil.to_dict("records"),
            "holdout": hold, "egri": D.egri_json(e), "semboller": tablo.to_dict("records"),
            "_islemler": D.havuz_islemler(sonuc)}


def saglik(d: dict, p: StratejiParam, r: RiskParam, m: MaliyetParam, ex, tohumlar=(0, 1, 2)) -> dict:
    out: dict = {}
    # (a1) Gerçek verinin getirileri karıştırılınca (trend yapısı yok edilince) kâr kalmamalı
    kar = []
    for t in tohumlar:
        s = D.toplu_calistir(d, p, r, m, karistir=t, ex=ex)
        kar.append({"tohum": t, **D.r_ozet(D.havuz_islemler(s)),
                    "karli_sembol_orani": float((D.sembol_tablosu(s)["toplam_getiri"] > 0).mean())})
    out["karistirilmis"] = kar
    # (a2) Saf rastgele yürüyüş
    rw = []
    from .backtest import calistir
    from .strateji import hazirla
    for t in range(20):
        df = veri.rastgele_yuruyus(30_000, tohum=1000 + t)
        if p.tetik_tf != "1h":
            df = veri.yeniden_ornekle(df, p.tetik_tf)
        btc = None
        if p.btc_filtre:  # "BTC" de bağımsız bir rastgele yürüyüş
            b = veri.rastgele_yuruyus(30_000, tohum=5000 + t)
            b = veri.yeniden_ornekle(b, p.tetik_tf) if p.tetik_tf != "1h" else b
            btc = hazirla(b, replace(p, btc_filtre=False))["rejim"]
        mt = calistir(df, p, r, m, btc_rejim=btc).metrik
        rw.append({"tohum": t, "toplam_getiri": mt["toplam_getiri"], "ort_r": mt["ort_r"], "islem": mt["islem"]})
    rwd = pd.DataFrame(rw)
    out["rastgele_yuruyus"] = {"n": len(rw), "medyan_getiri": float(rwd["toplam_getiri"].median()),
                               "karli_oran": float((rwd["toplam_getiri"] > 0).mean()),
                               "ort_r": float(rwd["ort_r"].mean()), "liste": rw}
    # (b) Sinyal kaydırma
    kay = {}
    for k in (-1, 0, 1, 2):
        s = D.toplu_calistir(d, p, r, m, kaydir=k, ex=ex)
        kay[str(k)] = {**D.r_ozet(D.havuz_islemler(s)), "portfoy": D.egri_metrik(D.portfoy_egrisi(s))}
    out["kaydirma"] = kay
    # Maliyet duyarlılığı
    mal = {}
    for ad, mm in {"maliyetsiz": replace(m, komisyon=0, kayma=0, fonlama_mod="yok"),
                   "yalniz_komisyon": replace(m, kayma=0, fonlama_mod="yok"),
                   "tam": m, "maker_benzeri": replace(m, komisyon=0.0002, kayma=0.0001),
                   "sabit_fonlama": replace(m, fonlama_mod="sabit")}.items():
        s = D.toplu_calistir(d, p, r, mm, ex=ex)
        mal[ad] = {**D.r_ozet(D.havuz_islemler(s)), "portfoy": D.egri_metrik(D.portfoy_egrisi(s))}
    out["maliyet_duyarliligi"] = mal
    return out


def uret(demo: bool = False, semboller: list[str] | None = None, hizli: bool = False, guncel50: bool = True,
         izgara_varyantlari: tuple[str, ...] = ("temel",), bitis: str = "2026-10",
         r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam()) -> dict:
    D.RAPOR_DIZINI = D.DEMO_RAPOR_DIZINI if demo else D.KOK / "raporlar"
    semboller = semboller or (["DEMO1", "DEMO2", "DEMO3", "DEMO4"] if demo else UZUN_SET)
    d = D.veri_seti(semboller, bitis=bitis, demo=demo)
    d = {s: v for s, v in d.items() if len(v[0]) > 3000}
    if "BTCUSDT" not in d:
        log.warning("BTCUSDT yok: BTC rejim varyantları atlanacak")
    rapor: dict = {"olusturma": pd.Timestamp.now(tz="UTC").isoformat(), "demo": demo,
                   "veri": {"kaynak": "sentetik" if demo else "Binance USDT-M resmi arşivi (data.binance.vision), 1s mum + gerçek fonlama",
                            "semboller": {s: [str(v[0].index[0]), str(v[0].index[-1]), len(v[0])] for s, v in d.items()},
                            "bitis": bitis},
                   "risk": asdict(r), "maliyet": asdict(m), "holdout": HOLDOUT}
    vs = varyantlar()
    if "BTCUSDT" not in d:
        vs = {k: v for k, v in vs.items() if not v.btc_filtre}
    if hizli:
        vs = {"temel": vs["temel"]}
    with D.havuz(d) as ex:
        rapor["varyantlar"] = {}
        islemler = {}
        for ad, p in vs.items():
            v = varyant_degerlendir(ad, p, d, r, m, ex)
            islemler[ad] = v.pop("_islemler")
            rapor["varyantlar"][ad] = v
        rapor["saglik"] = {ad: saglik(d, vs[ad], r, m, ex, tohumlar=(0,) if hizli else (0, 1, 2))
                           for ad in SAGLIK_VARYANTLARI if ad in vs}
        rapor["izgara"] = {}
        rapor["walk_forward"] = {}
        izg_alan = {"giris_n": [20, 40], "cikis_n": [10], "atr_kat": [3.0], "ema_n": [200]} if hizli else None
        test_yillari = [2022, 2023, 2024, 2025, 2026] if not demo else [2023, 2024]
        for ad in izgara_varyantlari:
            if ad not in vs:
                continue
            liste = D.izgara(d, vs[ad], r, m, ex, izg_alan)
            ozet = D.izgara_ozet(liste)
            temel_kw = {k: getattr(vs[ad], k) for k in liste[0]["param"]}
            wf = D.walk_forward(liste, test_yillari, 2, varsayilan=temel_kw)
            rapor["izgara"][ad] = {"ozet": ozet, "liste": [{"param": x["param"], **x["havuz_r"],
                                                            "portfoy_getiri": x["portfoy"].get("toplam_getiri"),
                                                            "portfoy_dd": x["portfoy"].get("max_dusus"),
                                                            "karli_sembol_orani": x["karli_sembol_orani"]} for x in liste]}
            rapor["walk_forward"][ad] = wf.to_dict("records")
            D.kaydet(f"izgara_{ad}.csv", pd.DataFrame([{**x["param"], **x["havuz_r"], "portfoy_getiri": x["portfoy"].get("toplam_getiri"),
                                                        "karli_sembol_orani": x["karli_sembol_orani"]} for x in liste]))
            D.kaydet(f"walk_forward_{ad}.csv", wf)
        rapor["kriterler"] = {ad: kriterler(v, rapor["izgara"].get(ad), rapor["walk_forward"].get(ad), rapor["saglik"].get(ad))
                              for ad, v in rapor["varyantlar"].items()}
    # Güncel ilk 50 (hacim, arşivden) — kısa geçmişli semboller dahil
    if guncel50 and not demo and not hizli:
        evren_yol = veri.VARSAYILAN_ONBELLEK / f"evren_{bitis}.json"
        if evren_yol.exists():
            ev = [s for s, _ in json.loads(evren_yol.read_text())]
            d50 = D.veri_seti(ev, bitis=bitis)
            d50 = {s: v for s, v in d50.items() if len(v[0]) > 24 * 60}
            p = vs["temel"]
            with D.havuz(d50) as ex:
                s50 = D.toplu_calistir(d50, p, r, m, ex=ex)
            t50 = D.sembol_tablosu(s50)
            D.kaydet("semboller_guncel50.csv", t50)
            rapor["guncel50"] = {"ozet": D.genel_ozet(s50), "semboller": t50.to_dict("records"),
                                 "not": "Bugünkü (2026-10) hacim sıralaması; her sembol kendi mevcut geçmişiyle. Hayatta kalma yanlılığı içerir."}
    D.kaydet("rapor.json", rapor)
    (D.RAPOR_DIZINI / "ozet.md").write_text(markdown_ozet(rapor))
    return rapor


# ------------------------------------------------------------------ markdown
def markdown_ozet(rp: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"_Oluşturma: {rp['olusturma'][:16]} UTC — veri: {rp['veri']['kaynak']}_\n")
    a("### Varyant karşılaştırması (ana set, tüm dönem, eşit ağırlıklı portföy)\n")
    a("| Varyant | İşlem | Kazanma | Ort. R | t | PF(R) | Portföy toplam | Yıllık | Max DD | Sharpe | Kârlı sembol | Kârlı yıl | Holdout ort. R (t) |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for ad, v in rp["varyantlar"].items():
        o = v["ozet"]
        hr, pf = o["havuz_r"], o["portfoy"]
        kar_yil = sum(1 for x in v["dilimler"] if (x.get("r_toplam_r") or 0) > 0)
        a(f"| {ad} | {hr['islem']} | {_fmt(hr['kazanma'], True)} | {_fmt(hr['ort_r'], n=3)} | {_fmt(hr.get('t'), n=1)} | {_fmt(hr['pf_r'])} | "
          f"{_fmt(pf.get('toplam_getiri'), True)} | {_fmt(pf.get('yillik_getiri'), True)} | {_fmt(pf.get('max_dusus'), True)} | "
          f"{_fmt(pf.get('sharpe'))} | {_fmt(o.get('karli_sembol_orani'), True)} | {kar_yil}/{len(v['dilimler'])} | "
          f"{_fmt(v['holdout'].get('r_ort_r'), n=3)} ({_fmt(v['holdout'].get('r_t'), n=1)}) |")
    if rp.get("kriterler"):
        a("\n### Ön kayıtlı 'canlıya uygun' kriterleri (DENEYLER.md §0)\n")
        anahtarlar = [k for k in next(iter(rp["kriterler"].values())) if k != "hepsi"]
        a("| Varyant | " + " | ".join(k.split("_", 1)[0] for k in anahtarlar) + " | Sonuç |")
        a("|---|" + "---|" * (len(anahtarlar) + 1))
        for ad, k in rp["kriterler"].items():
            hucre = ["✓" if k[x] else ("–" if k[x] is None else "✗") for x in anahtarlar]
            a(f"| {ad} | " + " | ".join(hucre) + f" | {'GEÇTİ' if k['hepsi'] else 'geçmedi'} |")
        a("\n1: ort. R>0 ve PF≥1.10 · 2: ≥5/7 yıl pozitif · 3: ≥%60 sembol kârlı · 4: ızgarada ≥%60 kombinasyon pozitif · "
          "5: walk-forward test ortalaması >0 ve ≥3/5 yıl pozitif · 6: holdout (2025-01→2026-10) ort. R>0 · "
          "7: karıştırılmış veride ort. R≤0.02 ve rastgele yürüyüşte medyan getiri<0 (– = bu varyant için çalıştırılmadı)")
    for ad, v in rp["varyantlar"].items():
        a(f"\n### Yıllık dilimler — {ad}  (`{v['ozet_metin']}`)\n")
        a("| Dilim | İşlem | Ort. R | t | Toplam R | Kazanma | Long R | Short R | Portföy getiri | Portföy DD | Kârlı sembol |")
        a("|---|---|---|---|---|---|---|---|---|---|---|")
        for x in v["dilimler"]:
            a(f"| {x['dilim']} | {x['r_islem']} | {_fmt(x['r_ort_r'], n=3)} | {_fmt(x.get('r_t'), n=1)} | {_fmt(x['r_toplam_r'], n=1)} | {_fmt(x['r_kazanma'], True)} | "
              f"{_fmt(x['long_r'], n=1)} | {_fmt(x['short_r'], n=1)} | {_fmt(x['portfoy_getiri'], True)} | {_fmt(x['portfoy_dd'], True)} | "
              f"{_fmt(x['karli_sembol_orani'], True)} |")
    t = rp["varyantlar"]["temel"]
    a("\n### Sembol bazında — temel (1000 USDT, %1 risk, 5x tavan, gerçek fonlama)\n")
    a("| Sembol | Başlangıç | Toplam | Yıllık | Max DD | Sharpe | İşlem | Kazanma | PF | Ort. R | Long $ | Short $ | Likidasyon | Al-tut |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for x in t["semboller"]:
        a(f"| {x['sembol']} | {x['baslangic']} | {_fmt(x['toplam_getiri'], True)} | {_fmt(x['yillik_getiri'], True)} | {_fmt(x['max_dusus'], True)} | "
          f"{_fmt(x['sharpe'])} | {x['islem']} | {_fmt(x['kazanma'], True)} | {_fmt(x['profit_factor'])} | {_fmt(x['ort_r'], n=3)} | "
          f"{_fmt(x['long_net'], n=0)} | {_fmt(x['short_net'], n=0)} | {x['likidasyon']} | {_fmt(x['al_tut'], True)} |")
    st = t["ozet"].get("istatistik", {})
    a(f"\nÇıkış nedenleri (temel): {st.get('cikis_nedenleri')} — likidasyon: {st.get('likidasyon')} — "
      f"toplam komisyon+kayma etkisi ve fonlama: komisyon {st.get('komisyon_toplam', 0):.0f} USDT, fonlama {st.get('fonlama_toplam', 0):.0f} USDT (tüm alt hesaplar)")
    for ad, wf in rp.get("walk_forward", {}).items():
        oz = rp["izgara"][ad]["ozet"]
        a(f"\n### Parametre sağlamlığı — {ad}\n")
        a(f"{oz['kombinasyon']} kombinasyon. Ort. R > 0 olan kombinasyon oranı: **{_fmt(oz['karli_kombinasyon_orani_R'], True)}**, "
          f"portföyü kârlı kombinasyon oranı: **{_fmt(oz['karli_kombinasyon_orani_portfoy'], True)}**. Medyan ort. R: {_fmt(oz['medyan_ort_r'], n=3)}, "
          f"medyan portföy getirisi: {_fmt(oz['medyan_portfoy_getiri'], True)}. En iyi/en kötü ort. R: {_fmt(oz['en_iyi_ort_r'], n=3)} / {_fmt(oz['en_kotu_ort_r'], n=3)}.\n")
        a("| Giriş N | Çıkış N | ATR kat | EMA | İşlem | Ort. R | Kazanma | Portföy | Kârlı sembol |")
        a("|---|---|---|---|---|---|---|---|---|")
        for x in sorted(rp["izgara"][ad]["liste"], key=lambda z: -z["ort_r"]):
            pp = x["param"]
            a(f"| {pp.get('giris_n')} | {pp.get('cikis_n')} | {pp.get('atr_kat')} | {pp.get('ema_n')} | {x['islem']} | {_fmt(x['ort_r'], n=3)} | "
              f"{_fmt(x['kazanma'], True)} | {_fmt(x['portfoy_getiri'], True)} | {_fmt(x['karli_sembol_orani'], True)} |")
        a(f"\n### Walk-forward — {ad} (2 yıl eğitimde seç → sonraki yıl test)\n")
        a("| Test yılı | Eğitim | Seçilen | Eğitim ort. R | Test ort. R | Test işlem | Varsayılan param test R | Tüm komb. test medyan R | Seçilenin test yüzdeliği |")
        a("|---|---|---|---|---|---|---|---|---|")
        for x in wf:
            sp = x["secilen"]
            a(f"| {x['test_yili']} | {x['egitim']} | {sp.get('giris_n')}/{sp.get('cikis_n')}/{sp.get('atr_kat')}/{sp.get('ema_n')} | "
              f"{_fmt(x['egitim_ort_r'], n=3)} | {_fmt(x['test_ort_r'], n=3)} | {x['test_islem']} | {_fmt(x.get('varsayilan_test_ort_r'), n=3)} | "
              f"{_fmt(x['test_tum_kombinasyon_medyan_r'], n=3)} | {_fmt(x['test_sirasi_yuzdelik'], True)} |")
        wfd = pd.DataFrame(wf)
        if len(wfd):
            a(f"\nWalk-forward birleşik test ort. R (yıllık ortalamalar): {_fmt(wfd['test_ort_r'].mean(), n=3)}; "
              f"testte pozitif yıl: {(wfd['test_ort_r'] > 0).sum()}/{len(wfd)}")
    for sad, s in rp["saglik"].items():
        a(f"\n### Sağlık kontrolleri — {sad}\n")
        a("| Test | İşlem | Ort. R | t | Toplam R | Not |")
        a("|---|---|---|---|---|---|")
        for x in s["karistirilmis"]:
            a(f"| Gerçek veri, getiriler karıştırılmış (tohum {x['tohum']}) | {x['islem']} | {_fmt(x['ort_r'], n=3)} | {_fmt(x.get('t'), n=1)} | {_fmt(x['toplam_r'], n=0)} | kârlı sembol {_fmt(x['karli_sembol_orani'], True)} |")
        rw = s["rastgele_yuruyus"]
        a(f"| Rastgele yürüyüş ({rw['n']} seri) | - | {_fmt(rw['ort_r'], n=3)} | - | - | medyan getiri {_fmt(rw['medyan_getiri'], True)}, kârlı oran {_fmt(rw['karli_oran'], True)} |")
        for k, x in s["kaydirma"].items():
            ad = {"-1": "Sinyal 1 mum ERKEN (gelecek bilgisi!)", "0": "Normal", "1": "Sinyal 1 mum geç", "2": "Sinyal 2 mum geç"}[k]
            a(f"| {ad} | {x['islem']} | {_fmt(x['ort_r'], n=3)} | {_fmt(x.get('t'), n=1)} | {_fmt(x['toplam_r'], n=0)} | portföy {_fmt(x['portfoy'].get('toplam_getiri'), True)} |")
        for k, x in s["maliyet_duyarliligi"].items():
            a(f"| Maliyet: {k} | {x['islem']} | {_fmt(x['ort_r'], n=3)} | {_fmt(x.get('t'), n=1)} | {_fmt(x['toplam_r'], n=0)} | portföy {_fmt(x['portfoy'].get('toplam_getiri'), True)} |")
    if "guncel50" in rp:
        g = rp["guncel50"]
        o = g["ozet"]
        a(f"\n### Güncel ilk 50 (temel, her sembol kendi geçmişiyle)\n")
        a(f"Sembol: {o['sembol_sayisi']}, kârlı sembol oranı: **{_fmt(o.get('karli_sembol_orani'), True)}**, medyan getiri {_fmt(o.get('medyan_toplam_getiri'), True)}, "
          f"havuz ort. R {_fmt(o['havuz_r']['ort_r'], n=3)} ({o['havuz_r']['islem']} işlem), likidasyon {o.get('likidasyon')}.\n")
        a("| Sembol | Başlangıç | Yıl | Toplam | Max DD | İşlem | Ort. R | PF | Al-tut |")
        a("|---|---|---|---|---|---|---|---|---|")
        for x in g["semboller"]:
            a(f"| {x['sembol']} | {x['baslangic']} | {x['yil']} | {_fmt(x['toplam_getiri'], True)} | {_fmt(x['max_dusus'], True)} | {x['islem']} | "
              f"{_fmt(x['ort_r'], n=3)} | {_fmt(x['profit_factor'])} | {_fmt(x['al_tut'], True)} |")
    return "\n".join(L) + "\n"
