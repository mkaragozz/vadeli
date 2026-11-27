"""Piyasa geneli veriler (yalnızca CANLI bağlam ve ısı haritası; sinyale girmez, çünkü ücretsiz geçmişi yok/kısa).

  * CoinGecko (anahtarsız, ücretsiz): toplam piyasa değeri, 24s değişim, BTC/ETH dominansı, stabilcoin payı,
    ilk N coinin 1s/24s/7g değişimi (ısı haritası).  İsteğe bağlı COINGECKO_API_KEY (demo anahtar) hız limitini artırır.
  * CoinMarketCap (CMC_API_KEY gerekli, isteğe bağlı): global metrikler.
  * CoinGlass (COINGLASS_API_KEY gerekli, isteğe bağlı): çoklu borsa toplam açık pozisyon / likidasyon.
  * TradingView KULLANILMAZ: resmi veri API'si yok, sayfa kazımak kullanım şartlarına aykırı.

Tüm çağrılar önbelleklidir (varsayılan 5 dk) ve hata durumunda son başarılı yanıt döner; tarayıcı bunlara bağımlı değildir.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger(__name__)
STABIL = {"tether", "usd-coin", "dai", "first-digital-usd", "ethena-usde", "usds", "paypal-usd", "true-usd"}


class Onbellekli:
    def __init__(self, sure: float = 300):
        self.sure = sure
        self._o: dict[str, tuple[float, Any]] = {}
        self.oturum = requests.Session()
        self.oturum.headers["User-Agent"] = "vadeli-tarayici/1.0"

    def _al(self, anahtar: str, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        simdi = time.time()
        kayit = self._o.get(anahtar)
        if kayit and simdi - kayit[0] < self.sure:
            return kayit[1]
        bekle = 2.0
        for deneme in range(3):
            try:
                r = self.oturum.get(url, params=params, headers=headers, timeout=20)
                if r.status_code == 429:
                    time.sleep(bekle * 5)
                    bekle *= 2
                    continue
                r.raise_for_status()
                v = r.json()
                self._o[anahtar] = (simdi, v)
                return v
            except (requests.RequestException, ValueError) as e:
                log.warning("%s alınamadı (%d/3): %s", anahtar, deneme + 1, type(e).__name__)
                time.sleep(bekle)
                bekle *= 2
        return kayit[1] if kayit else None  # eski veri (varsa) — bayatlık 'zaman' alanından görülür


def _stabil_mi(c: dict) -> bool:
    """Bilinen stabilcoinler + fiyatı ~1$ olup haftalık değişimi < %1 olanlar (yeni çıkan USD stabilcoinleri)."""
    if c.get("id") in STABIL:
        return True
    f, d7 = c.get("current_price"), c.get("price_change_percentage_7d_in_currency")
    return f is not None and 0.97 <= f <= 1.03 and d7 is not None and abs(d7) < 1.0


class CoinGecko(Onbellekli):
    URL = "https://api.coingecko.com/api/v3"

    def _h(self) -> dict:
        k = os.environ.get("COINGECKO_API_KEY")
        return {"x-cg-demo-api-key": k} if k else {}

    def genel(self) -> dict | None:
        g = self._al("cg_global", f"{self.URL}/global", headers=self._h())
        if not g:
            return None
        d = g["data"]
        pay = d.get("market_cap_percentage", {})
        return {"kaynak": "CoinGecko", "zaman": d.get("updated_at"),
                "toplam_piyasa_degeri": d["total_market_cap"].get("usd"),
                "toplam_hacim": d["total_volume"].get("usd"),
                "degisim_24s": d.get("market_cap_change_percentage_24h_usd"),
                "btc_dominans": pay.get("btc"), "eth_dominans": pay.get("eth"),
                "stabil_pay": sum(pay.get(k, 0) for k in ("usdt", "usdc", "dai", "fdusd", "usde"))}

    def isi_haritasi(self, n: int = 100) -> list[dict]:
        v = self._al(f"cg_markets_{n}", f"{self.URL}/coins/markets", headers=self._h(),
                     params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": min(n, 250), "page": 1,
                             "price_change_percentage": "1h,24h,7d", "sparkline": "false"})
        if not v:
            return []
        return [{"id": c["id"], "sembol": (c["symbol"] or "").upper(), "ad": c["name"], "fiyat": c.get("current_price"),
                 "piyasa_degeri": c.get("market_cap"), "hacim": c.get("total_volume"),
                 "d1s": c.get("price_change_percentage_1h_in_currency"),
                 "d24s": c.get("price_change_percentage_24h_in_currency"),
                 "d7g": c.get("price_change_percentage_7d_in_currency"),
                 "stabil": _stabil_mi(c)} for c in v]


class CoinMarketCap(Onbellekli):
    URL = "https://pro-api.coinmarketcap.com/v1"

    @property
    def etkin(self) -> bool:
        return bool(os.environ.get("CMC_API_KEY"))

    def genel(self) -> dict | None:
        if not self.etkin:
            return None
        v = self._al("cmc_global", f"{self.URL}/global-metrics/quotes/latest",
                     headers={"X-CMC_PRO_API_KEY": os.environ["CMC_API_KEY"]})
        if not v:
            return None
        d = v["data"]
        q = d["quote"]["USD"]
        return {"kaynak": "CoinMarketCap", "zaman": d.get("last_updated"), "toplam_piyasa_degeri": q.get("total_market_cap"),
                "degisim_24s": q.get("total_market_cap_yesterday_percentage_change"),
                "btc_dominans": d.get("btc_dominance"), "eth_dominans": d.get("eth_dominance")}


class CoinGlass(Onbellekli):
    """CoinGlass v4 açık API (anahtar gerekli). Yalnızca canlı bilgi kartı için: tüm borsalar toplam açık pozisyon."""

    URL = "https://open-api-v4.coinglass.com/api"

    @property
    def etkin(self) -> bool:
        return bool(os.environ.get("COINGLASS_API_KEY"))

    def acik_pozisyon(self, coin: str) -> dict | None:
        if not self.etkin:
            return None
        v = self._al(f"cg_oi_{coin}", f"{self.URL}/futures/open-interest/exchange-list", params={"symbol": coin},
                     headers={"CG-API-KEY": os.environ["COINGLASS_API_KEY"]})
        if not v or str(v.get("code")) != "0":
            return None
        return {"kaynak": "CoinGlass", "borsalar": v.get("data", [])[:10]}


class PiyasaBaglami:
    """Panonun 'Piyasa' ekranı için birleşik görünüm."""

    def __init__(self):
        self.cg = CoinGecko()
        self.cmc = CoinMarketCap()
        self.glass = CoinGlass()

    def ozet(self) -> dict:
        genel = self.cg.genel() or self.cmc.genel()
        return {"genel": genel, "cmc": self.cmc.genel() if self.cmc.etkin else None,
                "kaynaklar": {"coingecko": genel is not None, "coinmarketcap": self.cmc.etkin, "coinglass": self.glass.etkin},
                "not": "Piyasa geneli veriler bilgi amaçlıdır; sinyal üretiminde kullanılmaz (ücretsiz geçmişi yok, backtest edilemez)."}
