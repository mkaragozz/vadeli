"""Bildirimler: Telegram (birincil) ve isteğe bağlı Web Push (VAPID).

Gizli bilgiler YALNIZCA ortam değişkenlerinden okunur:
  TG_TOKEN, TG_CHAT                   Telegram bot anahtarı ve sohbet kimliği
  VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY Web Push anahtarları (bkz. README), VAPID_SUB (mailto:...)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import requests

from .ayarlar import Ayarlar
from .db import DB

log = logging.getLogger(__name__)
UYARI = "Kaldıraç zarar riskini büyütür; stop'u borsada gir. Yatırım tavsiyesi değildir."


def _f(x: float | None, n: int = 6) -> str:
    return "-" if x is None else f"{x:.{n}g}"


def sinyal_metni(x: dict) -> str:
    etiket = "YENİ" if x.get("yeni") else "devam"
    return (f"{'🟢' if x['yon'] == 'LONG' else '🔴'} {x['yon']} {x['sembol']} ({etiket})\n"
            f"Fiyat {_f(x['fiyat'])} · Stop {_f(x['stop'])} ({x['stop_yuzde']:.2f}%)\n"
            f"Kaldıraç {x['kaldirac']:.0f}x · Pozisyon {x['notional']:.0f}$ · Teminat {x['teminat']:.0f}$\n"
            f"Likidasyon {_f(x['likidasyon'])} · Risk {x['risk_usdt']:.2f}$ · 4s rejim {'+' if x['rejim'] > 0 else '-'}\n"
            f"Giriş: sonraki 1s mumun açılışı.\n{UYARI}")


def pozisyon_metni(u: dict) -> str:
    bas = {"cikis": "⚠️ ÇIKIŞ SİNYALİ", "liq_yakin": "🚨 LİKİDASYONA YAKIN", "stop_yakin": "⚠️ Stop'a yakın",
           "stop": "↗️ Stop güncelle"}.get(u["tur"], "Pozisyon")
    r = f"{u['r']:.2f}R" if u.get("r") is not None else "-"
    return (f"{bas}: {u['yon']} {u['sembol']} (#{u['id']})\nFiyat {_f(u.get('son_fiyat'))} · K/Z {u.get('pnl', 0):.2f}$ ({r})\n"
            f"Önerilen stop {_f(u.get('onerilen_stop'))} · Likidasyon {_f(u.get('likidasyon'))}\n{u.get('degerlendirme', '')}")


class Bildirici:
    def __init__(self, cfg: Ayarlar, db: DB):
        self.cfg = cfg
        self.db = db

    async def sinyal(self, x: dict) -> None:
        await self._gonder(sinyal_metni(x), baslik=f"{x['yon']} {x['sembol']}")

    async def pozisyon(self, u: dict) -> None:
        await self._gonder(pozisyon_metni(u), baslik=f"Pozisyon {u['sembol']}")

    async def _gonder(self, metin: str, baslik: str) -> None:
        if self.cfg.telegram and self.cfg.tg_token and self.cfg.tg_chat:
            await asyncio.to_thread(self._telegram, metin)
        if self.cfg.web_push:
            await asyncio.to_thread(self._web_push, baslik, metin)

    def _telegram(self, metin: str) -> None:
        url = f"https://api.telegram.org/bot{self.cfg.tg_token}/sendMessage"
        for deneme in range(3):
            try:
                r = requests.post(url, json={"chat_id": self.cfg.tg_chat, "text": metin}, timeout=15)
                if r.ok:
                    return
                log.warning("Telegram hatası %s", r.status_code)  # yanıt gövdesi anahtar içerebilir: loglanmaz
            except requests.RequestException as e:
                log.warning("Telegram gönderilemedi: %s", type(e).__name__)
            import time
            time.sleep(2 ** deneme)

    def _web_push(self, baslik: str, metin: str) -> None:
        ozel = os.environ.get("VAPID_PRIVATE_KEY")
        if not ozel:
            return
        try:
            from pywebpush import WebPushException, webpush  # isteğe bağlı bağımlılık
        except ImportError:
            log.warning("Web Push için 'pip install pywebpush' gerekli")
            return
        for ab in self.db.push_liste():
            try:
                webpush(ab, json.dumps({"baslik": baslik, "metin": metin}), vapid_private_key=ozel,
                        vapid_claims={"sub": os.environ.get("VAPID_SUB", "mailto:admin@localhost")})
            except WebPushException as e:
                if getattr(e, "response", None) is not None and e.response.status_code in (404, 410):
                    self.db.push_sil(ab["endpoint"])
                else:
                    log.warning("Web Push hatası: %s", type(e).__name__)
