"""Long/short vadeli backtest motoru.

Kurallar:
  * Sinyal i. mumun kapanışında, giriş (i+1). mumun AÇILIŞINDA (+ kayma).
  * Karşı kanal çıkışı da kapanışta oluşur, sonraki açılışta uygulanır.
  * Takip eden stop: her kapanışta  stop = max(stop, kapanış - k*ATR) (long; short tersi). Stop mum içinde
    tetiklenir: açılış stopun ötesindeyse açılıştan (boşluk), değilse stop fiyatından dolar (+ kayma).
  * Likidasyon: stop her zaman likidasyondan yakın olduğu için yalnızca açılış boşluğu likidasyonu aşarsa olur;
    bu durumda teminatın tamamı kaybedilir.
  * Fonlama: pozisyon fonlama anında (mum kapanışı) açıksa ödenir/alınır. "gercek" modda tarihsel oran ve işaret,
    "sabit" modda her 8 saatte bir sabit oran iki yönde de maliyet olarak.

`PozisyonTakip` sınıfı tek bir pozisyonun mum mum ilerletilmesidir; canlı pozisyon takibi ve geçmiş sinyal
sonuç simülasyonu da aynı sınıfı kullanır.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .strateji import MaliyetParam, RiskParam, StratejiParam, hazirla, ilk_stop, risk_hesapla

SAAT_MS = 3_600_000


@dataclass
class PozisyonTakip:
    yon: int                 # +1 long, -1 short
    giris: float             # gerçekleşen giriş fiyatı (kayma dahil)
    adet: float
    stop: float
    likidasyon: float
    teminat: float
    risk_usdt: float
    kaldirac: float
    giris_zaman: pd.Timestamp
    atr_kat: float
    maliyet: MaliyetParam
    ilk_stop: float = 0.0
    bekleyen_cikis: bool = False
    fonlama: float = 0.0     # toplam ödenen (+) / alınan (-) fonlama, USDT
    komisyon: float = 0.0
    mum_sayisi: int = 0
    en_iyi: float = 0.0      # pozisyon lehine görülen en uç fiyat (MFE için)
    basabas_r: float = 0.0   # >0: kapanış lehte bu kadar R gidince stop girişe (+iki yön maliyet) çekilir

    def __post_init__(self) -> None:
        self.ilk_stop = self.ilk_stop or self.stop
        self.en_iyi = self.giris

    # ---- yardımcılar
    def _kayma(self, fiyat: float, cikis: bool) -> float:
        """Aleyhe kayma: long girişte yukarı, long çıkışta aşağı."""
        isaret = -self.yon if cikis else self.yon
        return fiyat * (1 + isaret * self.maliyet.kayma)

    def gerceklesmemis(self, fiyat: float) -> float:
        return self.yon * self.adet * (fiyat - self.giris)

    def r_kati(self, fiyat: float) -> float:
        return (self.gerceklesmemis(fiyat) - self.fonlama - self.komisyon) / self.risk_usdt if self.risk_usdt else 0.0

    def onerilen_stop(self, kapanis: float, atr: float) -> float:
        """Takip eden stop kuralı: stop yalnızca pozisyon lehine hareket eder."""
        aday = kapanis - self.yon * self.atr_kat * atr
        return max(self.stop, aday) if self.yon == 1 else min(self.stop, aday)

    # ---- tek mum
    def acilis_isle(self, o: float) -> tuple[float, str] | None:
        """Mum açılışında: bekleyen çıkış, likidasyon boşluğu, stop boşluğu."""
        if self.bekleyen_cikis:
            return self._kayma(o, True), "kanal"
        if (self.yon == 1 and o <= self.likidasyon) or (self.yon == -1 and o >= self.likidasyon):
            return self.likidasyon, "likidasyon"
        if (self.yon == 1 and o <= self.stop) or (self.yon == -1 and o >= self.stop):
            return self._kayma(o, True), "stop"
        return None

    def mum_ici_isle(self, h: float, l: float) -> tuple[float, str] | None:
        if (self.yon == 1 and l <= self.stop) or (self.yon == -1 and h >= self.stop):
            return self._kayma(self.stop, True), "stop"
        self.en_iyi = max(self.en_iyi, h) if self.yon == 1 else min(self.en_iyi, l)
        return None

    def kapanis_isle(self, c: float, atr: float, cikis_sinyali: bool, fonlama_orani: float) -> None:
        """Kapanışta: fonlama, stop güncelleme, çıkış sinyali."""
        self.mum_sayisi += 1
        if fonlama_orani:
            notional = self.adet * c
            if self.maliyet.fonlama_mod == "sabit":
                self.fonlama += abs(fonlama_orani) * notional
            else:
                self.fonlama += self.yon * fonlama_orani * notional
        if math.isfinite(atr):
            self.stop = self.onerilen_stop(c, atr)
        if self.basabas_r > 0:
            mesafe = abs(self.giris - self.ilk_stop)
            if mesafe > 0 and self.yon * (c - self.giris) >= self.basabas_r * mesafe:
                bb = self.giris * (1 + self.yon * 2 * self.maliyet.tek_yon)
                self.stop = max(self.stop, bb) if self.yon == 1 else min(self.stop, bb)
        if cikis_sinyali:
            self.bekleyen_cikis = True

    def kapat(self, fiyat: float, neden: str) -> dict:
        cikis_kom = self.adet * fiyat * self.maliyet.komisyon
        self.komisyon += cikis_kom
        brut = self.gerceklesmemis(fiyat)
        if neden == "likidasyon":
            brut = -self.teminat  # teminatın tamamı
        net = brut - self.komisyon - self.fonlama
        return {"cikis_fiyat": fiyat, "neden": neden, "brut": brut, "net": net, "komisyon": self.komisyon,
                "fonlama": self.fonlama, "r": net / self.risk_usdt if self.risk_usdt else 0.0, "mum": self.mum_sayisi}


def pozisyon_ac(yon: int, acilis: float, atr_sinyal: float, zaman: pd.Timestamp, ozkaynak: float,
                p: StratejiParam, r: RiskParam, m: MaliyetParam) -> PozisyonTakip | None:
    """Sinyal mumunun ATR'si ile sonraki açılışta pozisyon aç."""
    if not (math.isfinite(atr_sinyal) and atr_sinyal > 0 and ozkaynak > 0):
        return None
    giris = acilis * (1 + yon * m.kayma)
    stop = ilk_stop(giris, yon, atr_sinyal, p)
    if stop <= 0:
        return None
    rk = risk_hesapla(giris, stop, yon, r, m, ozkaynak=ozkaynak)
    poz = PozisyonTakip(yon=yon, giris=giris, adet=rk["adet"], stop=stop, likidasyon=rk["likidasyon"],
                        teminat=rk["teminat"], risk_usdt=rk["risk_usdt"], kaldirac=rk["kaldirac"],
                        giris_zaman=zaman, atr_kat=p.atr_kat, maliyet=m, basabas_r=p.basabas_r)
    poz.komisyon = rk["notional"] * m.komisyon
    return poz


def fonlama_dizisi(index: pd.DatetimeIndex, fonlama: pd.Series | None, m: MaliyetParam, aralik_ms: int = SAAT_MS) -> np.ndarray:
    """Her mumun KAPANIŞ anında ödenen fonlama oranı (yoksa 0)."""
    kapanis = index + pd.Timedelta(milliseconds=aralik_ms)
    if m.fonlama_mod == "yok":
        return np.zeros(len(index))
    if m.fonlama_mod == "sabit" or fonlama is None or len(fonlama) == 0:
        saat = kapanis.hour
        dakika = kapanis.minute
        return np.where((saat % 8 == 0) & (dakika == 0), m.fonlama_8s, 0.0)
    f = fonlama.copy()
    f.index = f.index.floor("min")  # zaman damgası ms sapmalı olabiliyor
    f = f[~f.index.duplicated(keep="last")]
    if aralik_ms == SAAT_MS:
        return f.reindex(kapanis).fillna(0.0).values
    # büyük aralık: kapanıştan önceki aralıktaki tüm fonlamaların toplamı
    toplam = np.zeros(len(index))
    pos = np.searchsorted(kapanis.as_unit("ns").asi8, f.index.as_unit("ns").asi8, side="left")
    for k, v in zip(pos, f.values):
        if 0 <= k < len(index):
            toplam[k] += v
    return toplam


def _fonlama_modu(m: MaliyetParam, fonlama: pd.Series | None) -> MaliyetParam:
    """Gerçek oran yoksa temkinli sabit moda düş (iki yönde de maliyet)."""
    if m.fonlama_mod == "gercek" and (fonlama is None or len(fonlama) == 0):
        return replace(m, fonlama_mod="sabit")
    return m


@dataclass
class BacktestSonuc:
    sembol: str
    ozkaynak: pd.Series
    islemler: pd.DataFrame
    metrik: dict = field(default_factory=dict)


def calistir(df: pd.DataFrame, p: StratejiParam = StratejiParam(), r: RiskParam = RiskParam(),
             m: MaliyetParam = MaliyetParam(), fonlama: pd.Series | None = None, sembol: str = "",
             btc_rejim: pd.Series | None = None, hazir: pd.DataFrame | None = None,
             baslangic: pd.Timestamp | None = None, bitis: pd.Timestamp | None = None,
             kaydir: int = 0, ek: pd.DataFrame | None = None, btc_kapanis: pd.Series | None = None) -> BacktestSonuc:
    """Tek sembol backtest.
    `hazir`: önceden `hazirla` ile hesaplanmış veri (ızgara taramasında hız için).
    `baslangic/bitis`: göstergeler tüm veride ısınır, işlemler sadece bu aralıkta açılır (dilim/walk-forward).
    `kaydir`: SAĞLIK KONTROLÜ: sinyalleri k mum kaydırır (+1 = bir mum geç, -1 = bir mum erken = gelecek bilgisi)."""
    h = hazir if hazir is not None else hazirla(df, p, btc_rejim, ek, btc_kapanis)
    m = _fonlama_modu(m, fonlama)
    if baslangic is not None or bitis is not None:
        h = h.loc[baslangic:bitis]
    aralik_ms = SAAT_MS if p.tetik_tf == "1h" else int(pd.Timedelta(p.tetik_tf).total_seconds() * 1000)
    o, hi, lo, c = (h[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = h["atr"].to_numpy(float)
    ls, ss = h["long_sinyal"].to_numpy(bool), h["short_sinyal"].to_numpy(bool)
    if kaydir:
        ls = np.roll(ls, kaydir)
        ss = np.roll(ss, kaydir)
        if kaydir > 0:
            ls[:kaydir] = ss[:kaydir] = False
        else:
            ls[kaydir:] = ss[kaydir:] = False
    lc, sc = h["long_cikis"].to_numpy(bool), h["short_cikis"].to_numpy(bool)
    fon = fonlama_dizisi(h.index, fonlama, m, aralik_ms)
    idx = h.index
    n = len(h)
    nakit = r.hesap
    esp = np.empty(n)
    poz: PozisyonTakip | None = None
    bekleyen: tuple[int, int] | None = None  # (yön, sinyal satırı)
    islemler: list[dict] = []

    def kapat(i: int, fiyat: float, neden: str) -> None:
        nonlocal poz, nakit
        assert poz is not None
        sonuc = poz.kapat(fiyat, neden)
        nakit += sonuc["net"]
        islemler.append({"giris_zaman": poz.giris_zaman, "cikis_zaman": idx[i], "yon": "LONG" if poz.yon == 1 else "SHORT",
                         "giris": poz.giris, "ilk_stop": poz.ilk_stop, "kaldirac": poz.kaldirac, "teminat": poz.teminat,
                         "risk_usdt": poz.risk_usdt, "notional": poz.adet * poz.giris, **sonuc})
        poz = None

    for i in range(n):
        # 1) açılışta: bekleyen çıkış / boşluk
        if poz is not None:
            x = poz.acilis_isle(o[i])
            if x:
                kapat(i, *x)
        # 2) açılışta: bekleyen giriş
        if bekleyen is not None and poz is None:
            yon, j = bekleyen
            poz = pozisyon_ac(yon, o[i], a[j], idx[i], nakit, p, r, m)
        bekleyen = None
        # 3) mum içi ve kapanış
        if poz is not None:
            x = poz.mum_ici_isle(hi[i], lo[i])
            if x:
                kapat(i, *x)
            else:
                poz.kapanis_isle(c[i], a[i], bool(lc[i] if poz.yon == 1 else sc[i]), fon[i])
        # 4) kapanışta yeni sinyal (sonraki açılışta işlenecek)
        if i < n - 1 and (poz is None or poz.bekleyen_cikis):
            if ls[i] and (poz is None or poz.yon == -1):
                bekleyen = (1, i)
            elif ss[i] and (poz is None or poz.yon == 1):
                bekleyen = (-1, i)
        esp[i] = nakit + (poz.gerceklesmemis(c[i]) - poz.komisyon - poz.fonlama if poz else 0.0)
        if esp[i] <= 0:  # hesap bitti
            esp[i:] = 0
            break
    if poz is not None and n:  # dönem sonu: son kapanıştan kapat (rapor için)
        kapat(n - 1, poz._kayma(c[-1], True), "donem_sonu")
        esp[-1] = nakit
    ozk = pd.Series(esp, index=idx, name="ozkaynak")
    isl = pd.DataFrame(islemler)
    son = BacktestSonuc(sembol=sembol, ozkaynak=ozk, islemler=isl)
    son.metrik = metrikler(ozk, isl, r.hesap, c[0] if n else np.nan, c[-1] if n else np.nan)
    return son


def metrikler(ozk: pd.Series, isl: pd.DataFrame, hesap: float, ilk_fiyat: float, son_fiyat: float) -> dict:
    if ozk.empty:
        return {}
    yil = max((ozk.index[-1] - ozk.index[0]).total_seconds() / (365.25 * 86400), 1e-9)
    son = float(ozk.iloc[-1])
    toplam = son / hesap - 1
    yillik = (son / hesap) ** (1 / yil) - 1 if son > 0 else -1.0
    tepe = ozk.cummax()
    dd = float(((ozk - tepe) / tepe).min())
    gunluk = ozk.resample("1D").last().dropna()
    gr = gunluk.pct_change().dropna()
    sharpe = float(gr.mean() / gr.std() * math.sqrt(365)) if len(gr) > 2 and gr.std() > 0 else 0.0
    d: dict = {"baslangic": str(ozk.index[0].date()), "bitis": str(ozk.index[-1].date()), "yil": round(yil, 2),
               "toplam_getiri": toplam, "yillik_getiri": yillik, "max_dusus": dd, "sharpe": sharpe,
               "al_tut": son_fiyat / ilk_fiyat - 1 if ilk_fiyat else np.nan,
               "al_tut_yillik": (son_fiyat / ilk_fiyat) ** (1 / yil) - 1 if ilk_fiyat and son_fiyat > 0 else np.nan}
    d.update(islem_istatistik(isl))
    return d


def islem_istatistik(isl: pd.DataFrame) -> dict:
    if isl is None or isl.empty:
        return {"islem": 0, "kazanma": 0.0, "profit_factor": 0.0, "ort_r": 0.0, "long_islem": 0, "short_islem": 0,
                "long_net": 0.0, "short_net": 0.0, "likidasyon": 0, "cikis_nedenleri": {}, "fonlama_toplam": 0.0,
                "komisyon_toplam": 0.0, "ort_sure_saat": 0.0}
    kaz = isl.loc[isl["net"] > 0, "net"].sum()
    kay = -isl.loc[isl["net"] <= 0, "net"].sum()
    L = isl[isl["yon"] == "LONG"]
    S = isl[isl["yon"] == "SHORT"]
    return {
        "islem": int(len(isl)), "kazanma": float((isl["net"] > 0).mean()),
        "profit_factor": float(kaz / kay) if kay > 0 else float("inf"), "ort_r": float(isl["r"].mean()),
        "long_islem": int(len(L)), "short_islem": int(len(S)),
        "long_net": float(L["net"].sum()), "short_net": float(S["net"].sum()),
        "long_kazanma": float((L["net"] > 0).mean()) if len(L) else 0.0,
        "short_kazanma": float((S["net"] > 0).mean()) if len(S) else 0.0,
        "long_ort_r": float(L["r"].mean()) if len(L) else 0.0, "short_ort_r": float(S["r"].mean()) if len(S) else 0.0,
        "likidasyon": int((isl["neden"] == "likidasyon").sum()),
        "cikis_nedenleri": {k: int(v) for k, v in isl["neden"].value_counts().items()},
        "fonlama_toplam": float(isl["fonlama"].sum()), "komisyon_toplam": float(isl["komisyon"].sum()),
        "ort_sure_saat": float(isl["mum"].mean()),
    }


def tek_sinyal_simule(h: pd.DataFrame, sinyal_zamani: pd.Timestamp, yon: int, p: StratejiParam,
                      r: RiskParam = RiskParam(), m: MaliyetParam = MaliyetParam(),
                      fonlama: pd.Series | None = None) -> dict:
    """Geçmiş bir sinyalin sonucunu backtest ile AYNI kurallarla hesaplar.
    Döner: durum ('acik'|'kapali'|'bekliyor'), r, cikis_neden, sure_saat, giris, cikis_fiyat."""
    if sinyal_zamani not in h.index:
        return {"durum": "veri_yok"}
    i0 = h.index.get_loc(sinyal_zamani) + 1
    if i0 >= len(h):
        return {"durum": "bekliyor"}
    poz = pozisyon_ac(yon, float(h["open"].iloc[i0]), float(h["atr"].iloc[i0 - 1]), h.index[i0], r.hesap, p, r, m)
    if poz is None:
        return {"durum": "gecersiz"}
    m = _fonlama_modu(m, fonlama)
    fon = fonlama_dizisi(h.index, fonlama, m)
    cikis_col = "long_cikis" if yon == 1 else "short_cikis"
    for i in range(i0, len(h)):
        row = h.iloc[i]
        if i > i0:
            x = poz.acilis_isle(float(row["open"]))
            if x:
                s = poz.kapat(*x)
                return {"durum": "kapali", "giris": poz.giris, "cikis_zaman": h.index[i].isoformat(),
                        "sure_saat": i - i0, **s}
        x = poz.mum_ici_isle(float(row["high"]), float(row["low"]))
        if x:
            s = poz.kapat(*x)
            return {"durum": "kapali", "giris": poz.giris, "cikis_zaman": h.index[i].isoformat(),
                    "sure_saat": i - i0 + 1, **s}
        poz.kapanis_isle(float(row["close"]), float(row["atr"]), bool(row[cikis_col]), fon[i])
    son = float(h["close"].iloc[-1])
    return {"durum": "acik", "giris": poz.giris, "r": poz.r_kati(son), "stop": poz.stop, "sure_saat": len(h) - i0,
            "neden": "acik", "cikis_bekliyor": poz.bekleyen_cikis}
