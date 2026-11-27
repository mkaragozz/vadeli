"""Canlı tarayıcı, pozisyon değerlendirme, tekrar önleme, API güvenliği ve girdi doğrulama."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest

from vadeli import veri
from vadeli.ayarlar import Ayarlar, dogrula
from vadeli.borsa import DemoBorsa
from vadeli.canli import Tarayici
from vadeli.db import DB
from vadeli.uygulama import guvenli_mi


class SentetikBorsa(DemoBorsa):
    def __init__(self):
        self.hiz = 0
        self.veri = {f"T{i}USDT": veri.rastgele_yuruyus(5000, tohum=i, baslangic="2025-01-01", surukleme=0.0004 * (1 if i % 2 else -1))
                     for i in range(4)}
        self.saat_ms = int(pd.Timestamp("2025-06-01", tz="UTC").timestamp() * 1000)


@pytest.fixture()
def tarayici(tmp_path: Path):
    cfg = Ayarlar(veritabani=str(tmp_path / "t.db"), sinyal_csv=str(tmp_path / "s.csv"), websocket=False, sembol_sayisi=4,
                 tetik_tf="1h", btc_filtre=False, oi_teyit=False)
    db = DB(cfg.veritabani)
    return Tarayici(cfg, db, SentetikBorsa())


def test_tarama_ve_artimli_veri(tarayici):
    async def calis():
        await tarayici.evren_guncelle(zorla=True)
        await tarayici.tara()
        n1 = {s: len(df) for s, df in tarayici.mumlar.items()}
        for _ in range(30):
            await tarayici.borsa.sonraki_kapanisi_bekle(0)
            await tarayici.tara()
        return n1
    n1 = asyncio.run(calis())
    for s, df in tarayici.mumlar.items():
        assert df.index.is_monotonic_increasing and not df.index.duplicated().any()
        # son mum kapanmış olmalı ve sanal saatten önce
        assert df.index[-1] + pd.Timedelta(hours=1) <= pd.Timestamp(tarayici.borsa.simdi_ms(), unit="ms", tz="UTC")
    assert tarayici.durum["saglikli_sembol"] == 4
    # 30 tarama boyunca sinyal oluştuysa veritabanında ve CSV'de var
    sinyaller = tarayici.db.sinyaller()
    assert len(sinyaller) >= 1
    assert Path(tarayici.cfg.sinyal_csv).exists()
    # aynı sembol+yön+mum için tek kayıt
    anahtarlar = [(x["sembol"], x["yon"], x["zaman"]) for x in sinyaller]
    assert len(anahtarlar) == len(set(anahtarlar))


def test_bildirim_bir_kez(tarayici):
    assert tarayici.db.bildirim_ilk_mi("sinyal:X:LONG:t")
    assert not tarayici.db.bildirim_ilk_mi("sinyal:X:LONG:t")


def test_pozisyon_degerlendirme(tarayici):
    asyncio.run(tarayici.tara())
    s = next(iter(tarayici.hazir))
    h = tarayici.hazir[s]
    c = float(h["close"].iloc[-1])
    a = float(h["atr"].iloc[-1])
    p = {"id": 1, "sembol": s, "yon": "LONG", "giris": c, "adet": 1.0, "kaldirac": 5, "stop": c - 3 * a, "ilk_stop": c - 3 * a,
         "acilis": h.index[-1].isoformat()}
    d = tarayici.pozisyon_degerlendir(p, h)
    assert d["likidasyon"] == pytest.approx(c * (1 - 1 / 5 + 0.005))
    assert d["onerilen_stop"] >= p["stop"]
    # fiyat stopa çok yakınsa uyarı
    p2 = {**p, "giris": c + 2.5 * a, "stop": c - 0.2 * a, "ilk_stop": c - 0.2 * a}
    d2 = tarayici.pozisyon_degerlendir(p2, h)
    assert d2["stop_yakin"] == 1
    # short pozisyonda likidasyona yakınlık
    p3 = {**p, "yon": "SHORT", "giris": c / 1.15, "stop": c * 1.5, "ilk_stop": c * 1.5, "kaldirac": 5}
    d3 = tarayici.pozisyon_degerlendir(p3, h)
    assert d3["liq_yakin"] == 1 and "LİKİDASYON" in d3["degerlendirme"]


def test_guvenlik_kurali():
    assert guvenli_mi("127.0.0.1", None)[0]
    assert guvenli_mi("100.101.102.103", None)[0]          # Tailscale
    assert not guvenli_mi("0.0.0.0", None)[0]               # parolasız dış arayüz yasak
    assert not guvenli_mi("0.0.0.0", "kisa")[0]             # zayıf parola
    assert guvenli_mi("0.0.0.0", "uzun-ve-guclu-parola")[0]


def test_ayar_dogrulama():
    assert dogrula({"risk_yuzde": "1.5"}) == {"risk_yuzde": 1.5}
    for kotu in ({"risk_yuzde": 50}, {"hesap": "abc"}, {"veritabani": "/etc/passwd"}, {"telegram": "evet"}):
        with pytest.raises(ValueError):
            dogrula(kotu)


@pytest.fixture()
def istemci(tarayici, monkeypatch):
    from fastapi.testclient import TestClient

    from vadeli.pano import uygulama_olustur

    monkeypatch.setenv("PANO_PAROLA", "test-parolasi-uzun")
    asyncio.run(tarayici.tara())
    app = uygulama_olustur(tarayici, tarayici.cfg)
    return TestClient(app)


def test_api_giris_zorunlu_ve_deneme_siniri(istemci):
    assert istemci.get("/api/sinyaller").status_code == 401
    assert istemci.get("/api/oturum").json()["parola_gerekli"] is True
    for _ in range(5):
        assert istemci.post("/api/giris", json={"parola": "yanlis"}).status_code == 401
    assert istemci.post("/api/giris", json={"parola": "test-parolasi-uzun"}).status_code == 429  # kilit


def test_api_akis(istemci):
    r = istemci.post("/api/giris", json={"parola": "test-parolasi-uzun"})
    assert r.status_code == 200 and "vt_oturum" in r.cookies
    c = r.headers["set-cookie"].lower()
    assert "httponly" in c and "samesite=strict" in c
    v = istemci.get("/api/sinyaller").json()
    assert "aktif" in v and "yaklasan" in v
    s = v["evren"][0]["sembol"]
    m = istemci.get(f"/api/mumlar?sembol={s}&aralik=4h&limit=100").json()
    assert len(m["mumlar"]) > 50 and m["ema"]
    # girdi doğrulama
    assert istemci.get("/api/mumlar?sembol=<script>").status_code == 400
    assert istemci.get("/api/mumlar?sembol=BTCUSDT&aralik=1m").status_code == 422
    kotu = {"sembol": s, "yon": "LONG", "giris": 100, "notional": 100, "kaldirac": 5, "stop": 110}
    assert istemci.post("/api/pozisyonlar", json=kotu).status_code == 400          # stop yanlış tarafta
    assert istemci.post("/api/pozisyonlar", json={**kotu, "yon": "YUKARI"}).status_code == 422
    fiyat = m["mumlar"][-1][4]
    iyi = {"sembol": s, "yon": "LONG", "giris": fiyat, "notional": 200, "kaldirac": 5, "stop": fiyat * 0.97}
    r = istemci.post("/api/pozisyonlar", json=iyi)
    assert r.status_code == 200
    poz = r.json()["pozisyon"]
    assert poz["likidasyon"] and poz["degerlendirme"]
    assert istemci.post(f"/api/pozisyonlar/{poz['id']}/kapat", json={"fiyat": fiyat * 1.01}).json()["pozisyon"]["durum"] == "kapali"
    assert istemci.post("/api/ayarlar", json={"risk_yuzde": 99}).status_code == 400
    assert istemci.post("/api/ayarlar", json={"risk_yuzde": 0.5}).status_code == 200
    # köken kontrolü (CSRF)
    assert istemci.post("/api/ayarlar", json={"risk_yuzde": 0.5}, headers={"origin": "https://kotu.site"}).status_code == 403
    g = istemci.get("/api/gecmis").json()
    assert "istatistik" in g
    h = istemci.get("/")
    assert "Content-Security-Policy" in h.headers and "script-src 'self'" in h.headers["Content-Security-Policy"]


def test_emir_yok():
    """Kod tabanında emir gönderen ccxt çağrısı veya API anahtarı alanı bulunmamalı."""
    kok = Path(__file__).resolve().parent.parent / "vadeli"
    metin = "\n".join(p.read_text() for p in kok.glob("*.py"))
    for yasak in ("create_order", "createOrder", "fapiPrivate", "apiKey", "secret="):
        assert yasak not in metin, yasak


def test_4s_tetik_canli(tmp_path):
    cfg = Ayarlar(veritabani=str(tmp_path / "t.db"), sinyal_csv=str(tmp_path / "s.csv"), websocket=False, sembol_sayisi=4,
                  tetik_tf="4h", rejim_tf="4h", btc_filtre=False, oi_teyit=False)
    t = Tarayici(cfg, DB(cfg.veritabani), SentetikBorsa())

    async def calis():
        await t.evren_guncelle(zorla=True)
        for _ in range(12):
            await t.tara()
            await t.borsa.sonraki_kapanisi_bekle(0)
    asyncio.run(calis())
    for s, h in t.hazir.items():
        assert (h.index.hour % 4 == 0).all()
        assert h.index[-1] + pd.Timedelta(hours=4) <= pd.Timestamp(t.borsa.simdi_ms(), unit="ms", tz="UTC")
