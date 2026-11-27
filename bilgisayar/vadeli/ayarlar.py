"""Yapılandırma: config.toml + CLI bayrakları + ortam değişkenleri (gizli bilgiler YALNIZCA ortamdan)."""
from __future__ import annotations

import os
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .strateji import MaliyetParam, RiskParam, StratejiParam

KOK = Path(__file__).resolve().parent.parent


@dataclass
class Ayarlar:
    # hesap / risk (panodaki Ayarlar ekranından da değiştirilebilir, SQLite'a yazılır)
    hesap: float = 1000.0
    risk_yuzde: float = 1.0
    max_kaldirac: float = 5.0
    mmr: float = 0.005
    sembol_sayisi: int = 50
    # strateji
    giris_n: int = 20
    cikis_n: int = 10
    atr_n: int = 14
    atr_kat: float = 3.0
    ema_n: int = 200
    # Varsayılan: doğrulamada ön kayıtlı kriterleri geçen "4s_tetik_btc" varyantı (RAPOR.md).
    # Şartnamedeki orijinal 1s tetik için: tetik_tf = "1h", btc_filtre = false
    tetik_tf: str = "4h"
    rejim_tf: str = "4h"
    btc_filtre: bool = True
    yon: str = "ikisi"
    # Türev filtresi: DENEYLER.md §1'de kabul edilen tek filtre (kırılımda açık pozisyon artışı)
    oi_teyit: bool = True
    oi_n: int = 6
    fonlama_esik: float = 0.0
    kalabalik_z: float = 0.0
    taker_teyit: bool = False
    # maliyet
    komisyon: float = 0.0005
    kayma: float = 0.0003
    fonlama_8s: float = 0.0001
    # tarama
    tarama_gecikme_sn: float = 5.0          # mum kapanışından kaç saniye sonra taransın
    evren_yenileme_saat: float = 24.0       # sembol listesi yenileme aralığı
    gecmis_mum: int = 3000                  # ısınma için ilk yüklemede indirilen 1s mum sayısı
    websocket: bool = True
    # pano / ağ
    host: str = "127.0.0.1"
    port: int = 8000
    veritabani: str = str(KOK / "veri" / "tarayici.db")
    sinyal_csv: str = str(KOK / "sinyaller.csv")
    log_seviye: str = "INFO"
    # bildirim (anahtarlar ortam değişkeninden: TG_TOKEN, TG_CHAT, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY)
    telegram: bool = False
    web_push: bool = False
    zil: bool = True
    # güvenlik: PANO_PAROLA ortam değişkeni. Boşsa yalnızca 127.0.0.1/Tailscale arayüzünde çalışmaya izin verilir.
    guvenli_cerez: bool = False             # HTTPS arkasında (Caddy) True yapın
    telefon: str = "otomatik"               # "otomatik": Tailscale kuruluysa telefon için HTTPS adresi aç · "kapali"
    telefon_url: str | None = None          # çalışırken doldurulur

    # ---- türetilmiş
    def strateji(self) -> StratejiParam:
        return StratejiParam(giris_n=self.giris_n, cikis_n=self.cikis_n, atr_n=self.atr_n, atr_kat=self.atr_kat,
                             ema_n=self.ema_n, tetik_tf=self.tetik_tf, rejim_tf=self.rejim_tf,
                             btc_filtre=self.btc_filtre, yon=self.yon, oi_teyit=self.oi_teyit, oi_n=self.oi_n,
                             fonlama_esik=self.fonlama_esik, kalabalik_z=self.kalabalik_z, taker_teyit=self.taker_teyit)

    def risk(self) -> RiskParam:
        return RiskParam(hesap=self.hesap, risk_yuzde=self.risk_yuzde, max_kaldirac=self.max_kaldirac, mmr=self.mmr)

    def maliyet(self) -> MaliyetParam:
        return MaliyetParam(komisyon=self.komisyon, kayma=self.kayma, fonlama_8s=self.fonlama_8s)

    @property
    def parola(self) -> str | None:
        return os.environ.get("PANO_PAROLA") or None

    @property
    def tg_token(self) -> str | None:
        return os.environ.get("TG_TOKEN") or None

    @property
    def tg_chat(self) -> str | None:
        return os.environ.get("TG_CHAT") or None


# Panodan değiştirilebilen alanlar ve sınırları (girdi doğrulama)
DEGISEBILIR: dict[str, tuple[type, float, float]] = {
    "hesap": (float, 10, 10_000_000),
    "risk_yuzde": (float, 0.05, 5.0),
    "max_kaldirac": (float, 1, 50),
    "sembol_sayisi": (int, 1, 100),
    "telegram": (bool, 0, 1),
    "web_push": (bool, 0, 1),
    "zil": (bool, 0, 1),
}


def dogrula(degisiklik: dict) -> dict:
    temiz = {}
    for k, v in degisiklik.items():
        if k not in DEGISEBILIR:
            raise ValueError(f"Değiştirilemez ayar: {k}")
        tip, en_az, en_cok = DEGISEBILIR[k]
        if tip is bool:
            if not isinstance(v, bool):
                raise ValueError(f"{k}: true/false olmalı")
            temiz[k] = v
            continue
        try:
            x = tip(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k}: sayı olmalı") from None
        if not (en_az <= x <= en_cok):
            raise ValueError(f"{k}: {en_az} ile {en_cok} arasında olmalı")
        temiz[k] = x
    return temiz


def yukle(yol: Path | None = None, cli=None) -> Ayarlar:
    a = Ayarlar()
    if yol and Path(yol).exists():
        veri = tomllib.loads(Path(yol).read_text(encoding="utf-8"))
        duz: dict = {}
        for k, v in veri.items():
            if isinstance(v, dict):
                duz.update(v)
            else:
                duz[k] = v
        gecerli = {f.name for f in fields(a)}
        for k, v in duz.items():
            if k in gecerli:
                setattr(a, k, v)
    if cli is not None:
        for cli_ad, alan in (("hesap", "hesap"), ("risk", "risk_yuzde"), ("max_kaldirac", "max_kaldirac"),
                             ("sembol_sayisi", "sembol_sayisi"), ("host", "host"), ("port", "port")):
            v = getattr(cli, cli_ad, None)
            if v is not None:
                setattr(a, alan, v)
    return a
