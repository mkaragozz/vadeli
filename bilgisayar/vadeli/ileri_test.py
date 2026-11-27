"""İleri test (DENEYLER.md §3, ön kayıtlı): dondurulmuş strateji, hiçbir analizde kullanılmamış veride.

* Başlangıç 2026-11-01 00:00 UTC, evren ana set (22 sembol), kaynak Binance resmi arşivi (günlük ZIP'ler ertesi gün
  yayınlanır). Bilgisayarın açık olmasından bağımsızdır ve herkes aynı sonucu yeniden üretebilir.
* Backtest ile birebir aynı motor (`dogrulama._is` → `backtest.calistir`), aynı maliyetler.
* Karar kuralları önceden yazıldı (`karar`). Ara sonuçlara bakarak parametre değiştirilmez.

Çıktı: raporlar/ileri_test.json (panoda Geçmiş → İleri test)
"""
from __future__ import annotations

import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import dogrulama as D
from . import turev, veri
from .strateji import MaliyetParam, RiskParam, StratejiParam

log = logging.getLogger(__name__)

BASLANGIC = pd.Timestamp("2026-11-01", tz="UTC")
DOSYA = "ileri_test.json"
ILK_KARAR, ORTA_KARAR, SON_KARAR = 50, 100, 200


def dondurulmus() -> StratejiParam:
    """Canlı varsayılan (config.toml'daki kullanıcı ayarından bağımsız)."""
    from .ayarlar import Ayarlar

    return Ayarlar().strateji()


def evren() -> list[str]:
    from .rapor_uret import UZUN_SET

    return list(UZUN_SET)


def beklenti(p: StratejiParam, dizin: Path | None = None) -> dict | None:
    """Aynı sürümün 2022-2026 backtest beklentisi (ort. R ve işlem başı R standart sapması)."""
    dizin = dizin or D.RAPOR_DIZINI
    adaylar = []
    for ad in ("tur2.json", "turev.json"):
        yol = dizin / ad
        if not yol.exists():
            continue
        try:
            rp = json.loads(yol.read_text())
        except Exception:
            continue
        if ad == "tur2.json":
            adaylar.append(rp.get("taban"))
            adaylar += list(rp.get("varyantlar", {}).values())
        else:
            for x in rp.get("tabanlar", {}).values():
                adaylar.append(x.get("taban"))
                adaylar += list(x.get("filtreler", {}).values())
    for v in adaylar:
        if v and v.get("surum") == p.surum and v["r"].get("sd"):
            return {"ort_r": v["r"]["ort_r"], "sd": v["r"]["sd"], "islem": v["r"]["islem"],
                    "aylik_islem": v["r"]["islem"] / 58.0, "kaynak": "2022-01 → 2026-10 backtest"}
    return None


def karar(n: int, ort_r: float, kum_r: float, bek: dict | None) -> dict:
    """Ön kayıtlı kurallar (DENEYLER.md §3)."""
    alt_bant = None
    if bek and n:
        alt_bant = n * bek["ort_r"] - 2 * bek["sd"] * math.sqrt(n)
    uyari = alt_bant is not None and kum_r < alt_bant
    if n < ILK_KARAR:
        durum, metin = "erken", f"Erken: {n}/{ILK_KARAR} işlem. Karar için yeterli işlem yok; izlemeye devam."
    elif n < ORTA_KARAR:
        durum, metin = "izle", f"{n}/{ORTA_KARAR} işlem. 100. işlemde ilk karar verilecek."
    elif n < SON_KARAR:
        if ort_r <= 0:
            durum, metin = "dur", f"DUR: {n} işlemde ort. R {ort_r:+.3f} ≤ 0. Strateji ileri testte kenar göstermedi."
        else:
            durum, metin = "izle", f"100 işlem eşiği geçildi (ort. R {ort_r:+.3f} > 0). Son karar 200. işlemde."
    else:
        if ort_r > 0 and not uyari:
            durum, metin = "uygun", (f"{n} işlemde ort. R {ort_r:+.3f} > 0 ve beklenti bandı içinde: "
                                     "çok küçük riskle (%0.25–0.5/işlem) canlı denenebilir.")
        else:
            durum, metin = "dur", f"DUR: {n} işlemde ort. R {ort_r:+.3f} veya beklenti bandının altında."
    if uyari and durum not in ("dur",):
        metin += " ⚠ Kümülatif R beklenti bandının altında (backtest ile uyumsuz)."
    return {"durum": durum, "metin": metin, "uyari": bool(uyari), "alt_bant": alt_bant}


def _fonlama_tamamla(f: pd.Series, bitis: pd.Timestamp, oran: float) -> pd.Series:
    """Arşivde fonlama aylık yayınlanır; içinde bulunulan ay için tipik oran (+%0.01/8s: long öder, short alır)."""
    son = f.index.max() if len(f) else BASLANGIC - pd.Timedelta(hours=8)
    ek = pd.date_range(son.floor("8h") + pd.Timedelta(hours=8), bitis, freq="8h", tz="UTC")
    if not len(ek):
        return f
    return pd.concat([f, pd.Series(oran, index=ek)]).sort_index()


def veri_hazirla(semboller: list[str], simdi: pd.Timestamp | None = None) -> tuple[dict, dict, pd.Timestamp]:
    simdi = simdi or pd.Timestamp.now(tz="UTC")
    dun = (simdi.normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    son_ay = str(simdi.to_period("M") - 1)

    def yukle(s: str):
        df = veri.arsivden_mumlar(s, "1h", "2020-01", son_ay, gunluk_tamamla=True)
        f = veri.arsivden_fonlama(s, "2020-01", son_ay)
        m = turev.arsivden_metrik(s, bitis=dun, is_parcacigi=8)
        return s, df, f, m

    with ThreadPoolExecutor(4) as ex:
        sonuc = list(ex.map(yukle, semboller))
    son_veri = min((df.index[-1] for _, df, _, _ in sonuc if len(df)), default=BASLANGIC)
    bitis = son_veri + pd.Timedelta(hours=1)
    d = {s: (df, _fonlama_tamamla(f, bitis, MaliyetParam().fonlama_8s)) for s, df, f, _ in sonuc if len(df)}
    # Tüm semboller aynı ana kadar: en geç gelen sembolün son mumu
    d = {s: (df[df.index <= son_veri], f) for s, (df, f) in d.items()}
    metrik = {s: m for s, _, _, m in sonuc}
    return d, metrik, son_veri


def hesapla(d: dict, metrik: dict, son_veri: pd.Timestamp, p: StratejiParam | None = None,
            r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam(), dizin: Path | None = None) -> dict:
    p = p or dondurulmus()
    with D.havuz(d, n=2, metrik=metrik, baslangic=BASLANGIC) as ex:
        sonuc = D.toplu_calistir(d, p, r, m, ex=ex)
    isl = D.havuz_islemler(sonuc)
    if isl.empty:
        isl = pd.DataFrame(columns=["giris_zaman", "cikis_zaman", "yon", "r", "neden", "sembol"])
    kapali = isl[isl["neden"] != "donem_sonu"].sort_values("cikis_zaman")
    acik = isl[isl["neden"] == "donem_sonu"].sort_values("giris_zaman")
    ozet = D.r_ozet(kapali)
    bek = beklenti(p, dizin)
    kum = kapali["r"].cumsum().to_numpy() if len(kapali) else np.array([])
    egri = []
    for i, (z, k) in enumerate(zip(kapali["cikis_zaman"], kum), start=1):
        e = {"n": i, "zaman": pd.Timestamp(z).isoformat(), "kum_r": float(k)}
        if bek:
            e["beklenen"] = i * bek["ort_r"]
            e["alt"] = i * bek["ort_r"] - 2 * bek["sd"] * math.sqrt(i)
            e["ust"] = i * bek["ort_r"] + 2 * bek["sd"] * math.sqrt(i)
        egri.append(e)
    k = karar(ozet["islem"], ozet["ort_r"], float(kum[-1]) if len(kum) else 0.0, bek)

    def kayit(x) -> dict:
        return {"sembol": x.sembol, "yon": x.yon, "giris_zaman": pd.Timestamp(x.giris_zaman).isoformat(),
                "cikis_zaman": pd.Timestamp(x.cikis_zaman).isoformat(), "giris": float(x.giris),
                "ilk_stop": float(x.ilk_stop), "cikis_fiyat": float(x.cikis_fiyat), "r": float(x.r),
                "neden": x.neden}

    gun = max((son_veri - BASLANGIC).total_seconds() / 86400, 1e-9)
    return D._json_uyumlu({
        "surum": p.surum, "strateji": p.ozet(), "baslangic": BASLANGIC.isoformat(),
        "son_veri": (son_veri + pd.Timedelta(hours=1)).isoformat(), "olusturma": time.strftime("%Y-%m-%dT%H:%M UTC", time.gmtime()),
        "evren": sorted(d), "gun": gun, "ozet": ozet, "long": D.r_ozet(kapali[kapali["yon"] == "LONG"]),
        "short": D.r_ozet(kapali[kapali["yon"] == "SHORT"]), "beklenti": bek, "karar": k, "egri": egri,
        "beklenen_islem": (bek["aylik_islem"] * gun / 30.44) if bek else None,
        "islemler": [kayit(x) for x in kapali.itertuples(index=False)][::-1],
        "acik": [kayit(x) for x in acik.itertuples(index=False)],
        "kurallar": [f"< {ILK_KARAR} işlem: erken, karar yok",
                     "Kümülatif R, beklenen − 2σ√n bandının altına düşerse: uyarı",
                     f"{ORTA_KARAR}. işlem: ort. R ≤ 0 ise DUR",
                     f"{SON_KARAR}. işlem: ort. R > 0 ve bant üstünde ise küçük riskle canlı uygun, değilse DUR"],
    })


def uret(dizin: Path | None = None) -> dict:
    d, metrik, son = veri_hazirla(evren())
    rp = hesapla(d, metrik, son, dizin=dizin)
    D.kaydet(DOSYA, rp, dizin)
    return rp


def metin(rp: dict) -> str:
    o = rp["ozet"]
    b = rp.get("beklenti") or {}
    L = [f"İleri test — {rp['strateji']} ({rp['surum']})",
         f"Dönem: {rp['baslangic'][:10]} → {rp['son_veri'][:16]} UTC ({rp['gun']:.0f} gün), {len(rp['evren'])} sembol",
         f"Kapanan işlem: {o['islem']}  ort. R {o['ort_r']:+.3f}  toplam {o['toplam_r']:+.1f} R  kazanma %{o['kazanma'] * 100:.0f}"
         + (f"   (beklenti ort. R {b['ort_r']:+.3f}, ~{rp['beklenen_islem']:.0f} işlem)" if b else ""),
         f"Açık: {len(rp['acik'])}",
         f"KARAR: {rp['karar']['metin']}"]
    return "\n".join(L)
