"""Canlı veri kaynakları.

* `BinanceBorsa`: ccxt.binanceusdm REST (herkese açık) + fstream WebSocket kline akışı. Anahtar yok, emir yok.
* `DemoBorsa`: Binance'e bağlanmadan, önbellekteki GERÇEK arşiv verisini (yoksa sentetik veriyi) hızlandırılmış
  saatle tekrar oynatır. Pano ve tarayıcının tüm akışını denemek için.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import AsyncIterator, Callable

import pandas as pd

from . import veri

log = logging.getLogger(__name__)
SAAT_MS = 3_600_000


class Borsa:
    ad = "soyut"
    canli = True

    def simdi_ms(self) -> int:
        return int(time.time() * 1000)

    def evren(self, n: int) -> list[dict]:
        raise NotImplementedError

    def mumlar(self, sembol: str, aralik: str = "1h", baslangic_ms: int | None = None, toplam: int | None = None) -> pd.DataFrame:
        raise NotImplementedError

    async def sonraki_kapanisi_bekle(self, gecikme_sn: float) -> None:
        simdi = time.time()
        hedef = (int(simdi // 3600) + 1) * 3600 + gecikme_sn
        await asyncio.sleep(max(0.5, hedef - simdi))

    def metrik(self, sembol: str, alanlar: tuple[str, ...] | None = None) -> pd.DataFrame:
        """Saatlik türev konumlanma verisi (turev.METRIK_SUTUN)."""
        return pd.DataFrame()

    def fonlama(self, sembol: str) -> pd.Series:
        """Gerçekleşmiş fonlama oranları (son ~30 gün)."""
        return pd.Series(dtype=float)

    async def kline_akisi(self, semboller: list[str], geri_cagir: Callable[[str, list], None],
                          durum: dict) -> None:
        """Kapanan mumları geri_cagir(sembol, [t,o,h,l,c,v,qv]) ile iletir. Kopunca yeniden bağlanır."""
        return None


class BinanceBorsa(Borsa):
    ad = "binance"
    WS = "wss://fstream.binance.com/stream?streams="

    def __init__(self) -> None:
        from .turev import BinanceMetrikREST

        self.rest = veri.BinanceREST()
        self._metrik = BinanceMetrikREST(self.rest)

    def metrik(self, sembol: str, alanlar: tuple[str, ...] | None = None) -> pd.DataFrame:
        return self._metrik.metrik(sembol, alanlar) if alanlar else self._metrik.metrik(sembol)

    def fonlama(self, sembol: str) -> pd.Series:
        return self.rest.fonlama(sembol, int(time.time() * 1000) - 30 * 86_400_000)

    def evren(self, n: int) -> list[dict]:
        return self.rest.evren(n)

    def mumlar(self, sembol: str, aralik: str = "1h", baslangic_ms: int | None = None, toplam: int | None = None) -> pd.DataFrame:
        return self.rest.mumlar(sembol, aralik, baslangic_ms=baslangic_ms, toplam=toplam)

    async def kline_akisi(self, semboller, geri_cagir, durum) -> None:
        import websockets

        bekle = 1.0
        while True:
            liste = list(semboller)  # evren değişirse yeniden bağlanırken güncellenir
            if not liste:
                await asyncio.sleep(5)
                continue
            url = self.WS + "/".join(f"{s.lower()}@kline_1h" for s in liste[:200])
            try:
                async with websockets.connect(url, open_timeout=20, ping_interval=60, ping_timeout=60, max_size=2**22) as ws:
                    durum.update(ws_bagli=True, ws_hata=None, ws_sembol=len(liste))
                    log.info("WebSocket bağlandı (%d sembol)", len(liste))
                    bekle = 1.0
                    baslangic = time.time()
                    async for ham in ws:
                        m = json.loads(ham)
                        k = m.get("data", {}).get("k")
                        durum["ws_son_mesaj"] = time.time()
                        if k and k.get("x"):
                            geri_cagir(k["s"], [int(k["t"]), k["o"], k["h"], k["l"], k["c"], k["v"], k["q"]])
                        if set(semboller) != set(liste) or time.time() - baslangic > 23 * 3600:
                            break  # evren değişti veya Binance'in 24 saatlik kesmesinden önce tazele
            except asyncio.CancelledError:
                raise
            except Exception as e:  # ağ kopması vb.
                durum.update(ws_bagli=False, ws_hata=str(e)[:200])
                log.warning("WebSocket koptu: %s — %.0f sn sonra yeniden", e, bekle)
                await asyncio.sleep(bekle + random.random())
                bekle = min(bekle * 2, 120)
            finally:
                durum["ws_bagli"] = False


class DemoBorsa(Borsa):
    """Önbellekteki gerçek arşivi hızlandırılmış saatle oynatır (1 saat = `hiz` saniye)."""

    ad = "demo"
    canli = False

    def __init__(self, hiz: float = 3.0, baslangic: str = "2026-09-01", onbellek: Path = veri.VARSAYILAN_ONBELLEK):
        self.hiz = hiz
        self.veri: dict[str, pd.DataFrame] = {}
        for yol in sorted(onbellek.glob("*_1h.csv")):
            if "_metrik" in yol.name:
                continue
            s = yol.name.split("_")[0]
            try:
                df = veri._csv_oku(yol)
            except Exception:
                continue
            if len(df) > 4000 and df.index[-1] > pd.Timestamp(baslangic, tz="UTC"):
                self.veri[s] = df
        if not self.veri:  # önbellek yoksa sentetik
            for i in range(12):
                self.veri[f"DEMO{i + 1}USDT"] = veri.rastgele_yuruyus(8000, tohum=i, baslangic="2025-11-01",
                                                                    surukleme=0.0001 * (1 if i % 2 else -1))
            baslangic = str(veri.rastgele_yuruyus(8000).index[6000].date())
        self.saat_ms = int(pd.Timestamp(baslangic, tz="UTC").timestamp() * 1000)
        log.info("Demo: %d sembol, sanal saat %s", len(self.veri), pd.Timestamp(self.saat_ms, unit="ms", tz="UTC"))

    def simdi_ms(self) -> int:
        return self.saat_ms + 5_000

    def _kes(self, df: pd.DataFrame) -> pd.DataFrame:
        return veri.kapanmamislari_at(df[df.index < pd.Timestamp(self.simdi_ms(), unit="ms", tz="UTC")], "1h", self.simdi_ms())

    def evren(self, n: int) -> list[dict]:
        out = []
        for s, df in self.veri.items():
            d = self._kes(df).iloc[-24:]
            if len(d):
                out.append({"sembol": s, "hacim24": float(d["quote_volume"].sum()), "fiyat": float(d["close"].iloc[-1])})
        out.sort(key=lambda x: -x["hacim24"])
        return out[:n]

    def mumlar(self, sembol, aralik="1h", baslangic_ms=None, toplam=None):
        df = self.veri.get(sembol)
        if df is None:
            return veri.bos_df()
        d = self._kes(df)
        if aralik != "1h":
            d = veri.yeniden_ornekle(d, aralik)
        if baslangic_ms is not None:
            d = d[d.index >= pd.Timestamp(baslangic_ms, unit="ms", tz="UTC")]
        if toplam:
            d = d.iloc[-toplam:]
        return d

    def metrik(self, sembol: str, alanlar: tuple[str, ...] | None = None) -> pd.DataFrame:
        yol = veri.VARSAYILAN_ONBELLEK / f"{sembol}_metrik_1h.csv"
        if not yol.exists():
            return pd.DataFrame()
        m = veri._csv_oku(yol)
        sinir = pd.Timestamp(self.simdi_ms(), unit="ms", tz="UTC").floor("h")
        return m[m.index < sinir].iloc[-24 * 30:]

    def fonlama(self, sembol: str) -> pd.Series:
        yol = veri.VARSAYILAN_ONBELLEK / f"{sembol}_fonlama.csv"
        if not yol.exists():
            return pd.Series(dtype=float)
        f = veri._csv_oku(yol).iloc[:, 0]
        return f[f.index <= pd.Timestamp(self.simdi_ms(), unit="ms", tz="UTC")].iloc[-100:]

    async def sonraki_kapanisi_bekle(self, gecikme_sn: float) -> None:
        await asyncio.sleep(self.hiz)
        self.saat_ms += SAAT_MS
