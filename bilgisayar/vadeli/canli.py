"""Canlı tarayıcı: evren seçimi, artımlı mum deposu, 1s kapanış taraması, pozisyon değerlendirme,
geçmiş sinyal sonuçları, bildirimler. Sinyal mantığı strateji.hazirla'dadır (backtest ile aynı).

Sistem asla emir göndermez.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import veri
from .ayarlar import Ayarlar
from .backtest import tek_sinyal_simule
from .borsa import Borsa
from .db import DB
from .strateji import StratejiParam, hazirla, likidasyon_fiyati, son_sinyaller

log = logging.getLogger(__name__)
# Doğrulanan ana set (RAPOR.md). Bu set dışındaki coinlerde kenar çok daha zayıf (2022 evreni testi, DENEYLER.md D14).
ANA_SET = frozenset(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT",
                     "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BCHUSDT", "ETCUSDT", "ATOMUSDT", "FILUSDT", "AAVEUSDT", "XLMUSDT",
                     "NEARUSDT", "UNIUSDT", "ZECUSDT", "SANDUSDT"])
SAAT_MS = 3_600_000
YAKINLIK = 0.30  # mesafenin %30'undan az kaldıysa uyar


class Yayinci:
    """SSE için basit yayın: her bağlı istemciye bir kuyruk."""

    def __init__(self) -> None:
        self.kuyruklar: set[asyncio.Queue] = set()

    def abone(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.kuyruklar.add(q)
        return q

    def ayril(self, q: asyncio.Queue) -> None:
        self.kuyruklar.discard(q)

    def yayinla(self, olay: str, veri_: Any = None) -> None:
        for q in list(self.kuyruklar):
            try:
                q.put_nowait((olay, veri_))
            except asyncio.QueueFull:
                pass


class Tarayici:
    def __init__(self, cfg: Ayarlar, db: DB, borsa: Borsa, bildirici=None, yayinci: Yayinci | None = None,
                 terminal: Callable[["Tarayici", list[dict]], None] | None = None):
        self.cfg = cfg
        self.db = db
        self.borsa = borsa
        self.bildirici = bildirici
        self.yayinci = yayinci or Yayinci()
        self.terminal = terminal
        self.mumlar: dict[str, pd.DataFrame] = {}
        self.hazir: dict[str, pd.DataFrame] = {}
        self.evren: list[dict] = []
        self.evren_zaman = 0.0
        self.aktif: list[dict] = []
        self.yaklasan: list[dict] = []
        self.ws_kuyruk: dict[str, list[list]] = {}
        self.durum: dict[str, Any] = {"basladi": time.time(), "son_tarama": None, "tarama_suresi": None,
                                      "son_mum": None, "gecikme_sn": None, "ws_bagli": False, "hatali": {},
                                      "kaynak": borsa.ad, "tarama_sayisi": 0, "saglikli_sembol": 0, "sembol": 0}
        self._ws_gorev: asyncio.Task | None = None
        self.metrikler: dict[str, tuple[int, pd.DataFrame]] = {}   # sembol -> (çekildiği tf mumu, saatlik metrik)
        self.fonlamalar: dict[str, tuple[int, pd.Series]] = {}
        self._ws_semboller: list[str] = []
        self.ayarlari_uygula()

    # ------------------------------------------------------------ ayarlar
    def ayarlari_uygula(self) -> None:
        """Panodan kaydedilen ayarlar sonraki taramada devreye girer."""
        for k, v in self.db.ayarlar_oku().items():
            if hasattr(self.cfg, k):
                setattr(self.cfg, k, v)
        self.p = self.cfg.strateji()
        self.r = self.cfg.risk()
        self.m = self.cfg.maliyet()

    # ------------------------------------------------------------ veri
    @property
    def tf_ms(self) -> int:
        return veri.ARALIK_MS[self.p.tetik_tf]

    def tetik_verisi(self, df1h: pd.DataFrame) -> pd.DataFrame:
        """1s depodan stratejinin tetik zaman dilimine (eksik son dilim atılarak)."""
        return df1h if self.p.tetik_tf == "1h" else veri.yeniden_ornekle(df1h, self.p.tetik_tf)

    def btc_rejim(self) -> pd.Series | None:
        if not self.p.btc_filtre:
            return None
        df = self.mumlar.get("BTCUSDT")
        if df is None or len(df) < 300:
            return None
        sade = StratejiParam(giris_n=self.p.giris_n, cikis_n=self.p.cikis_n, atr_n=self.p.atr_n, atr_kat=self.p.atr_kat,
                             ema_n=self.p.ema_n, tetik_tf=self.p.tetik_tf, rejim_tf=self.p.rejim_tf)
        return hazirla(self.tetik_verisi(df), sade)["rejim"]

    def turev_guncelle(self, sembol: str) -> None:
        """Türev filtresi için açık pozisyon (ve gerekirse diğer) metrikleri: her yeni tetik mumunda bir kez çekilir."""
        if not self.p.turev_gerekli:
            return
        tf_mum = self.borsa.simdi_ms() // self.tf_ms
        kayit = self.metrikler.get(sembol)
        if kayit and kayit[0] == tf_mum:
            return
        alanlar = tuple(a for a, gerek in (("oi", self.p.oi_teyit), ("ls_hesap", bool(self.p.kalabalik_z)),
                                           ("taker_oran", self.p.taker_teyit)) if gerek)
        try:
            m = self.borsa.metrik(sembol, alanlar)
            self.metrikler[sembol] = (tf_mum, m)
            if self.p.fonlama_esik:
                self.fonlamalar[sembol] = (tf_mum, self.borsa.fonlama(sembol))
        except Exception as e:  # metrik yoksa teyit filtresi sinyali engeller (güvenli taraf)
            self.durum["hatali"][sembol] = f"türev: {str(e)[:150]}"

    def hazirla_sembol(self, df1h: pd.DataFrame, btc: pd.Series | None = None, sembol: str | None = None) -> pd.DataFrame:
        """Backtest ile aynı: strateji.hazirla (tetik zaman diliminde) + aynı türev özellikleri."""
        from . import turev

        if self.p.btc_filtre and btc is None:
            btc = self.btc_rejim()
            if btc is None:
                btc = pd.Series(0, index=df1h.index)  # BTC verisi yoksa filtre hiçbir sinyale izin vermez
        dt = self.tetik_verisi(df1h)
        ek = None
        if self.p.turev_gerekli:
            m = self.metrikler.get(sembol, (0, None))[1] if sembol else None
            f = self.fonlamalar.get(sembol, (0, None))[1] if sembol else None
            ek = turev.ozellikler(m, f, dt.index, self.p.tetik_tf, oi_n=self.p.oi_n)
        return hazirla(dt, self.p, btc, ek)

    def _izlenen(self) -> list[str]:
        s = [e["sembol"] for e in self.evren]
        if self.p.btc_filtre and "BTCUSDT" not in s:
            s.append("BTCUSDT")
        for p in self.db.pozisyonlar(acik=True):
            if p["sembol"] not in s:
                s.append(p["sembol"])
        for x in self.db.sinyaller(200, acik_degil=True):
            if x["sembol"] not in s:
                s.append(x["sembol"])
        return s

    async def evren_guncelle(self, zorla: bool = False) -> None:
        if not zorla and self.evren and time.time() - self.evren_zaman < self.cfg.evren_yenileme_saat * 3600:
            return
        try:
            yeni = await asyncio.to_thread(self.borsa.evren, int(self.cfg.sembol_sayisi))
            if yeni:
                self.evren = yeni
                self.evren_zaman = time.time()
                log.info("Evren güncellendi: %d sembol", len(yeni))
        except Exception as e:
            log.error("Evren alınamadı: %s", e)
            if not self.evren:
                raise

    async def _mum_tamamla(self, s: str, sem: asyncio.Semaphore) -> None:
        """Bellek → SQLite → REST sırasıyla; yalnızca EKSİK mumlar indirilir."""
        async with sem:
            try:
                df = self.mumlar.get(s)
                if df is None:
                    df = await asyncio.to_thread(self.db.mum_oku, s, "1h", self.cfg.gecmis_mum)
                # WebSocket'ten gelenleri ekle
                gelen = self.ws_kuyruk.pop(s, [])
                if gelen:
                    df = veri.temizle(pd.concat([df, veri.satirlardan_df(gelen)])) if len(df) else veri.satirlardan_df(gelen)
                simdi = self.borsa.simdi_ms()
                son_kapanmis_acilis = (simdi // SAAT_MS - 1) * SAAT_MS
                if df.empty or len(df) < min(self.cfg.gecmis_mum, 1000):
                    yeni = await asyncio.to_thread(self.borsa.mumlar, s, "1h", None, self.cfg.gecmis_mum)
                    df = yeni
                    await asyncio.to_thread(self.db.mum_yaz, s, "1h", yeni)
                else:
                    son_t = int(df.index[-1].timestamp() * 1000)
                    if son_t < son_kapanmis_acilis:
                        yeni = await asyncio.to_thread(self.borsa.mumlar, s, "1h", son_t + SAAT_MS, None)
                        if not yeni.empty:
                            df = veri.temizle(pd.concat([df, yeni]))
                            await asyncio.to_thread(self.db.mum_yaz, s, "1h", yeni)
                    elif gelen:
                        await asyncio.to_thread(self.db.mum_yaz, s, "1h", veri.satirlardan_df(gelen))
                df = veri.kapanmamislari_at(df, "1h", simdi).iloc[-self.cfg.gecmis_mum:]
                self.mumlar[s] = df
                self.durum["hatali"].pop(s, None)
            except Exception as e:  # tek sembol hatası taramayı durdurmaz
                self.durum["hatali"][s] = str(e)[:200]
                log.warning("%s verisi alınamadı: %s", s, e)

    def ws_mum(self, sembol: str, satir: list) -> None:
        self.ws_kuyruk.setdefault(sembol, []).append(satir)
        self.durum["son_ws_mum"] = time.time()

    async def _ws_yonet(self) -> None:
        if not self.cfg.websocket or not self.borsa.canli:
            return
        self._ws_semboller[:] = self._izlenen()
        if self._ws_gorev is None or self._ws_gorev.done():
            self._ws_gorev = asyncio.create_task(self.borsa.kline_akisi(self._ws_semboller, self.ws_mum, self.durum))

    # ------------------------------------------------------------ tarama
    async def tara(self) -> list[dict]:
        t0 = time.time()
        self.ayarlari_uygula()
        await self.evren_guncelle()
        await self._ws_yonet()
        semboller = self._izlenen()
        sem = asyncio.Semaphore(6)
        await asyncio.gather(*(self._mum_tamamla(s, sem) for s in semboller))
        hacim = {e["sembol"]: e["hacim24"] for e in self.evren}
        evren_set = set(hacim)
        aktif, yaklasan, yeni_sinyaller = [], [], []
        simdi = self.borsa.simdi_ms()
        beklenen_son = pd.Timestamp((simdi // SAAT_MS - 1) * SAAT_MS, unit="ms", tz="UTC")
        beklenen_tf = pd.Timestamp((simdi // self.tf_ms - 1) * self.tf_ms, unit="ms", tz="UTC")
        btc = await asyncio.to_thread(self.btc_rejim) if self.p.btc_filtre else None
        saglikli = 0
        for s in semboller:
            df = self.mumlar.get(s)
            if df is None or len(df) < 300:
                continue
            if df.index[-1] >= beklenen_son:
                saglikli += 1
            try:
                if s in evren_set:
                    await asyncio.to_thread(self.turev_guncelle, s)
                h = await asyncio.to_thread(self.hazirla_sembol, df, btc, s)
            except Exception as e:
                self.durum["hatali"][s] = f"hazirla: {e}"
                continue
            self.hazir[s] = h
            if s not in evren_set:
                continue
            if df.index[-1] < beklenen_son or h.index[-1] < beklenen_tf:  # bayat veriyle sinyal üretme
                continue
            for x in son_sinyaller(h, self.r, self.m, self.p):
                x.update(sembol=s, hacim24=hacim.get(s, 0.0), tetik_tf=self.p.tetik_tf, ana_set=s in ANA_SET,
                         yas_saat=round((simdi - (int(h.index[-1].timestamp() * 1000) + self.tf_ms)) / SAAT_MS, 2))
                if x["tur"] == "sinyal":
                    aktif.append(x)
                    sid = self.db.sinyal_ekle({**x, "fiyat": x["fiyat"], "stop": x["stop"]})
                    x["id"] = sid
                    if sid is not None:
                        self._csv_ekle(x)
                    if self.db.bildirim_ilk_mi(f"sinyal:{s}:{x['yon']}:{x['zaman']}"):
                        yeni_sinyaller.append(x)
                else:
                    yaklasan.append(x)
        self.aktif, self.yaklasan = aktif, yaklasan
        poz_uyari = self.pozisyonlari_degerlendir()
        self.gecmis_sonuclari_guncelle()
        son_mum = max((df.index[-1] for df in self.mumlar.values() if len(df)), default=None)
        self.durum.update(son_tarama=time.time(), tarama_suresi=round(time.time() - t0, 2),
                          son_mum=son_mum.isoformat() if son_mum is not None else None,
                          gecikme_sn=round(simdi / 1000 - (son_mum.timestamp() + 3600), 1) if son_mum is not None else None,
                          saglikli_sembol=saglikli, sembol=len(semboller), tarama_sayisi=self.durum["tarama_sayisi"] + 1,
                          sanal_saat=pd.Timestamp(simdi, unit="ms", tz="UTC").isoformat() if not self.borsa.canli else None)
        if self.bildirici:
            for x in yeni_sinyaller:
                await self.bildirici.sinyal(x)
            for u in poz_uyari:
                await self.bildirici.pozisyon(u)
        self.yayinci.yayinla("tarama", {"durum": self.durum_ozet(), "yeni": len(yeni_sinyaller)})
        if self.terminal:
            self.terminal(self, yeni_sinyaller)
        log.info("Tarama: %d sembol, %d sinyal (%d yeni bildirim), %d yaklaşan, %.1fs",
                 len(semboller), len(aktif), len(yeni_sinyaller), len(yaklasan), time.time() - t0)
        return aktif

    def _csv_ekle(self, x: dict) -> None:
        yol = Path(self.cfg.sinyal_csv)
        yeni = not yol.exists()
        try:
            with yol.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if yeni:
                    w.writerow(["zaman", "sembol", "yon", "fiyat", "stop", "yeni", "kaldirac", "param_surum"])
                w.writerow([x["zaman"], x["sembol"], x["yon"], f"{x['fiyat']:.8g}", f"{x['stop']:.8g}",
                            int(x["yeni"]), x["kaldirac"], x["param_surum"]])
        except OSError as e:
            log.warning("sinyaller.csv yazılamadı: %s", e)

    # ------------------------------------------------------------ pozisyonlar
    def pozisyon_degerlendir(self, p: dict, h: pd.DataFrame | None) -> dict:
        """Kullanıcının girdiği pozisyonu son kapanmış muma göre değerlendirir (backtest çıkış kurallarıyla)."""
        yon = 1 if p["yon"] == "LONG" else -1
        liq = likidasyon_fiyati(p["giris"], yon, max(1.0, p["kaldirac"]), self.r.mmr)
        out: dict = {"likidasyon": liq}
        if h is None or h.empty:
            out["degerlendirme"] = "veri yok"
            return out
        son = h.iloc[-1]
        c, a = float(son["close"]), float(son["atr"])
        ilk = p.get("ilk_stop") or p["stop"]
        risk = abs(p["giris"] - ilk) * p["adet"]
        pnl = yon * p["adet"] * (c - p["giris"])
        # Takip eden stop: girişten bu yana her kapanışta (kapanış - k*ATR)'nin en iyisi, mevcut stoptan geri gitmez
        acilis = pd.Timestamp(p["acilis"])
        acilis = acilis.tz_localize("UTC") if acilis.tzinfo is None else acilis
        sonra = h[h.index >= acilis.floor(self.p.tetik_tf)]
        if len(sonra):
            aday = sonra["close"] - yon * self.p.atr_kat * sonra["atr"]
            iz = float(aday.max() if yon == 1 else aday.min())
        else:
            iz = c - yon * self.p.atr_kat * a
        oneri = max(p["stop"], iz) if yon == 1 else min(p["stop"], iz)
        cikis = bool(son["long_cikis"] if yon == 1 else son["short_cikis"])
        stop_kalan = (c - p["stop"]) * yon
        stop_toplam = abs(p["giris"] - ilk)
        liq_kalan = (c - liq) * yon
        liq_toplam = abs(p["giris"] - liq)
        stop_yakin = stop_kalan < YAKINLIK * stop_toplam
        liq_yakin = liq_kalan < YAKINLIK * liq_toplam
        notlar = []
        if stop_kalan <= 0:
            notlar.append("Fiyat stop seviyesini geçti: borsadaki stop dolmuş olmalı, kontrol edin.")
        elif stop_yakin:
            notlar.append("Stop'a yakın (mesafenin %30'undan az kaldı).")
        if liq_yakin:
            notlar.append("LİKİDASYONA YAKIN!")
        if cikis:
            notlar.append(f"ÇIKIŞ SİNYALİ: {self.p.cikis_n} mumluk karşı kanal kırıldı (sonraki açılışta çıkış).")
        stop_degisti = (oneri - p["stop"]) * yon > 1e-12
        if stop_degisti:
            notlar.append(f"Stopu {oneri:.6g} seviyesine çekin.")
        out.update(son_fiyat=c, pnl=pnl, r=pnl / risk if risk > 0 else None, onerilen_stop=oneri,
                   cikis_sinyali=int(cikis), stop_yakin=int(stop_yakin), liq_yakin=int(liq_yakin),
                   degerlendirme=" ".join(notlar) or "Normal.", _stop_degisti=stop_degisti, _zaman=h.index[-1].isoformat())
        return out

    def pozisyonlari_degerlendir(self) -> list[dict]:
        uyarilar = []
        for p in self.db.pozisyonlar(acik=True):
            d = self.pozisyon_degerlendir(p, self.hazir.get(p["sembol"]))
            onceki = dict(p)
            stop_degisti = d.pop("_stop_degisti", False)
            zaman = d.pop("_zaman", "")
            self.db.pozisyon_guncelle(p["id"], d)
            temel = {"id": p["id"], "sembol": p["sembol"], "yon": p["yon"], **d}
            if d.get("cikis_sinyali") and self.db.bildirim_ilk_mi(f"poz:{p['id']}:cikis:{zaman}"):
                uyarilar.append({**temel, "tur": "cikis"})
            if d.get("liq_yakin") and not onceki.get("liq_yakin"):
                uyarilar.append({**temel, "tur": "liq_yakin"})
            if d.get("stop_yakin") and not onceki.get("stop_yakin"):
                uyarilar.append({**temel, "tur": "stop_yakin"})
            if stop_degisti and self.db.bildirim_ilk_mi(f"poz:{p['id']}:stop:{zaman}"):
                uyarilar.append({**temel, "tur": "stop"})
        if uyarilar:
            self.yayinci.yayinla("pozisyon", uyarilar)
        return uyarilar

    # ------------------------------------------------------------ geçmiş sinyaller
    def gecmis_sonuclari_guncelle(self) -> None:
        for x in self.db.sinyaller(500, acik_degil=True):
            h = self.hazir.get(x["sembol"])
            if h is None:
                continue
            t = pd.Timestamp(x["zaman"])
            if t < h.index[0]:
                self.db.sinyal_sonuc_yaz(x["id"], {"durum": "kapali", "neden": "veri_yok"})
                continue
            yon = 1 if x["yon"] == "LONG" else -1
            try:
                sonuc = tek_sinyal_simule(h, t, yon, self.p, self.r, self.m)
            except Exception as e:
                log.debug("sonuç hesaplanamadı %s: %s", x["id"], e)
                continue
            if sonuc.get("durum") in ("kapali", "acik"):
                self.db.sinyal_sonuc_yaz(x["id"], sonuc)

    # ------------------------------------------------------------ özetler (API)
    def durum_ozet(self) -> dict:
        d = dict(self.durum)
        d["hatali_sayi"] = len(d.pop("hatali", {}))
        d["aktif"] = len(self.aktif)
        d["yaklasan"] = len(self.yaklasan)
        return d

    # ------------------------------------------------------------ döngü
    async def calis(self) -> None:
        log.info("Tarayıcı başlıyor (%s)", self.borsa.ad)
        bekle = 5.0
        while True:  # borsaya ulaşılamazsa çökmeden, geri çekilerek yeniden dene
            try:
                await self.evren_guncelle(zorla=True)
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                metin = str(e)
                if "451" in metin or "restricted location" in metin:
                    neden = ("Binance bu konumdan hizmet vermiyor (HTTP 451). Tarayıcıyı Binance'in hizmet verdiği "
                             "bir bölgedeki bilgisayar/sunucuda çalıştırın.")
                else:
                    neden = f"Binance'e ulaşılamadı ({type(e).__name__}). İnternet bağlantısını kontrol edin."
                self.durum["son_hata"] = neden
                log.error("%s Ayrıntı: %s", neden, metin[:300])
                print(f"HATA: {neden} {bekle:.0f} sn sonra yeniden denenecek.", flush=True)
                self.yayinci.yayinla("tarama", {"durum": self.durum_ozet(), "yeni": 0})
                await asyncio.sleep(bekle)
                bekle = min(bekle * 2, 300)
        while True:
            try:
                await self.tara()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("Tarama hatası: %s", e)
                self.durum["son_hata"] = str(e)[:300]
            await self.borsa.sonraki_kapanisi_bekle(self.cfg.tarama_gecikme_sn)
