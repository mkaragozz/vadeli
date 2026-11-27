"""Tek süreç: tarayıcı döngüsü + FastAPI panosu (uvicorn) aynı asyncio döngüsünde."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import sys

from .ayarlar import Ayarlar
from .bildirim import UYARI, Bildirici
from .borsa import BinanceBorsa, DemoBorsa
from .canli import Tarayici, Yayinci
from .db import DB
from .terminal import tablo_yaz

log = logging.getLogger(__name__)


def guvenli_mi(host: str, parola: str | None) -> tuple[bool, str]:
    """Korumasız açık port YOK: dış arayüzde parola zorunlu. Tailscale (100.64.0.0/10) arayüzüne parolasız
    bağlanmaya izin verilir (yalnızca kullanıcının kendi cihazları erişebilir), yine de parola önerilir."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return True, "yerel"
    try:
        ip = ipaddress.ip_address(host)
        if ip in ipaddress.ip_network("100.64.0.0/10") or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48"):
            return True, "tailscale" + ("" if parola else " (parolasız: yalnız Tailnet cihazları erişebilir)")
    except ValueError:
        pass
    if parola:
        if len(parola) < 12:
            return False, "PANO_PAROLA en az 12 karakter olmalı"
        return True, "parola korumalı"
    return False, (f"{host} dış arayüzdür. Parolasız açılamaz: PANO_PAROLA ortam değişkenini ayarlayın "
                   "veya Tailscale IP'sini kullanın (README > Uzaktan erişim).")


def calistir(cfg: Ayarlar, demo: bool = False, demo_hiz: float = 3.0, pano: bool = True, terminal: bool = True) -> int:
    tamam, neden = guvenli_mi(cfg.host, cfg.parola)
    if pano and not tamam:
        print(f"GÜVENLİK: {neden}", file=sys.stderr)
        return 2
    if demo:
        cfg.veritabani = cfg.veritabani.replace(".db", "_demo.db")
        cfg.sinyal_csv = cfg.sinyal_csv.replace(".csv", "_demo.csv")
        cfg.websocket = False
    db = DB(cfg.veritabani)
    borsa = DemoBorsa(hiz=demo_hiz) if demo else BinanceBorsa()
    yayinci = Yayinci()
    tarayici = Tarayici(cfg, db, borsa, Bildirici(cfg, db), yayinci, tablo_yaz if terminal else None)
    print(f"{UYARI}\nVeri kaynağı: {'DEMO (arşiv tekrarı, Binance bağlantısı yok)' if demo else 'Binance USDT-M (herkese açık uç noktalar)'}"
          f"\nSistem emir göndermez; API anahtarı kullanmaz.")
    if pano and cfg.host in ("127.0.0.1", "localhost", "::1"):
        from . import telefon

        cfg.telefon_sonuc = telefon.hazirla(cfg.port, cfg.telefon)
        cfg.telefon_url = cfg.telefon_sonuc.get("url")
    if pano:
        print(f"Pano: http://{cfg.host if ':' not in cfg.host else '[' + cfg.host + ']'}:{cfg.port}  ({neden})")

    async def ana():
        gorevler = [asyncio.create_task(tarayici.calis())]
        if pano:
            import uvicorn

            from .pano import uygulama_olustur

            app = uygulama_olustur(tarayici, cfg)
            sunucu = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="warning",
                                                   proxy_headers=True, forwarded_allow_ips="127.0.0.1"))
            gorevler.append(asyncio.create_task(sunucu.serve()))
        done, _ = await asyncio.wait(gorevler, return_when=asyncio.FIRST_COMPLETED)
        for g in gorevler:
            g.cancel()
        for g in done:
            if g.exception():
                raise g.exception()

    try:
        asyncio.run(ana())
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    return 0
