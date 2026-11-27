"""FastAPI arka ucu: API + SSE + statik PWA arayüzü + giriş/oturum güvenliği.

Güvenlik:
  * Varsayılan dinleme 127.0.0.1. Dış arayüzde (0.0.0.0, VPS) PANO_PAROLA ortam değişkeni ZORUNLU (uygulama.py).
  * Parola varsa tüm /api uçları oturum çerezi ister. Oturum: rastgele 256 bit belirteç, HttpOnly, SameSite=Strict,
    HTTPS arkasında Secure. Hatalı girişte IP başına deneme sınırı.
  * Tüm girdiler pydantic ile doğrulanır; arayüz verileri textContent ile basar (HTML kaçışı), CSP ile satır içi betik yok.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import secrets
import subprocess
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import ayarlar as A
from . import veri
from .bildirim import UYARI
from .canli import Tarayici
from .dogrulama import DEMO_RAPOR_DIZINI, RAPOR_DIZINI


def rapor_yolu() -> Path:
    """Gerçek veri raporu varsa o, yoksa demo raporu."""
    y = RAPOR_DIZINI / "rapor.json"
    return y if y.exists() else DEMO_RAPOR_DIZINI / "rapor.json"
from .strateji import ema, rejim_hizala

log = logging.getLogger(__name__)
KOK = Path(__file__).resolve().parent.parent
STATIK = KOK / "static"
OTURUM_SURE = 14 * 86400
CEREZ = "vt_oturum"


# ------------------------------------------------------------------ modeller (girdi doğrulama)
class GirisIstek(BaseModel):
    parola: str = Field(min_length=1, max_length=256)


class PozisyonIstek(BaseModel):
    sembol: str = Field(min_length=3, max_length=30)
    yon: Literal["LONG", "SHORT"]
    giris: float = Field(gt=0, lt=1e9)
    adet: float | None = Field(default=None, gt=0, lt=1e12)
    notional: float | None = Field(default=None, gt=0, lt=1e9)
    kaldirac: float = Field(ge=1, le=125)
    stop: float = Field(gt=0, lt=1e9)
    sinyal_id: int | None = Field(default=None, ge=1)
    not_metni: str = Field(default="", max_length=1000)

    @field_validator("sembol")
    @classmethod
    def _s(cls, v: str) -> str:
        return veri.sembol_dogrula(v)


class PozisyonGuncelle(BaseModel):
    stop: float | None = Field(default=None, gt=0, lt=1e9)
    not_metni: str | None = Field(default=None, max_length=1000)


class KapatIstek(BaseModel):
    fiyat: float = Field(gt=0, lt=1e9)


class PushIstek(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("endpoint https olmalı")
        return v


class BacktestIstek(BaseModel):
    hizli: bool = True


# ------------------------------------------------------------------ yardımcılar
def _temiz(x):
    """JSON için NaN/inf -> None, numpy -> python."""
    if isinstance(x, dict):
        return {k: _temiz(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_temiz(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def istatistik(satirlar: list[dict]) -> dict:
    k = [x for x in satirlar if x.get("durum") == "kapali" and x.get("r") is not None]
    if not k:
        return {"islem": 0}
    r = np.array([x["r"] for x in k], dtype=float)
    kaz, kay = r[r > 0].sum(), -r[r <= 0].sum()
    return {"islem": len(k), "kazanma": float((r > 0).mean()), "ort_r": float(r.mean()), "toplam_r": float(r.sum()),
            "pf_r": float(kaz / kay) if kay > 0 else None,
            "ort_sure_saat": float(np.mean([x.get("sure_saat") or 0 for x in k]))}


def uygulama_olustur(tarayici: Tarayici, cfg: A.Ayarlar) -> FastAPI:
    app = FastAPI(title="Vadeli Sinyal Tarayıcı", docs_url=None, redoc_url=None, openapi_url=None)
    db = tarayici.db
    oturumlar: dict[str, float] = {}
    hatalar: dict[str, deque] = defaultdict(deque)
    bt_durum: dict = {"calisiyor": False}

    def _ip(req: Request) -> str:
        # Caddy arkasında gerçek IP X-Forwarded-For'da; yalnızca yerel vekil arkasında güvenilir
        if req.client and req.client.host in ("127.0.0.1", "::1"):
            return req.headers.get("x-forwarded-for", "127.0.0.1").split(",")[0].strip()
        return req.client.host if req.client else "?"

    def _oturum_gecerli(req: Request) -> bool:
        if not cfg.parola:
            return True
        t = req.cookies.get(CEREZ)
        if not t:
            return False
        bitis = oturumlar.get(t)
        if not bitis or bitis < time.time():
            oturumlar.pop(t, None)
            return False
        return True

    @app.middleware("http")
    async def guvenlik(req: Request, call_next):
        yol = req.url.path
        acik = yol in ("/api/giris", "/api/oturum") or not yol.startswith("/api/")
        if not acik and not _oturum_gecerli(req):
            return JSONResponse({"hata": "giriş gerekli"}, status_code=401)
        # CSRF: durum değiştiren isteklerde aynı köken
        if req.method in ("POST", "PATCH", "DELETE", "PUT"):
            koken = req.headers.get("origin")
            if koken and koken.split("://", 1)[-1] != req.headers.get("host", ""):
                return JSONResponse({"hata": "köken reddedildi"}, status_code=403)
        yanit = await call_next(req)
        yanit.headers["X-Content-Type-Options"] = "nosniff"
        yanit.headers["X-Frame-Options"] = "DENY"
        yanit.headers["Referrer-Policy"] = "no-referrer"
        yanit.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                    "img-src 'self' data:; connect-src 'self' https://data-api.binance.vision https://api.binance.com "
                                                    "https://fapi.binance.com; frame-ancestors 'none'; base-uri 'none'")
        if yol.startswith("/api/"):
            yanit.headers["Cache-Control"] = "no-store"
        return yanit

    # ---------------------------------------------------------- giriş
    @app.get("/api/oturum")
    async def oturum(req: Request):
        return {"parola_gerekli": bool(cfg.parola), "giris_yapildi": _oturum_gecerli(req)}

    @app.post("/api/giris")
    async def giris(req: Request, g: GirisIstek, resp: Response):
        if not cfg.parola:
            return {"tamam": True}
        ip = _ip(req)
        q = hatalar[ip]
        simdi = time.time()
        while q and q[0] < simdi - 900:
            q.popleft()
        if len(q) >= 5:
            raise HTTPException(429, "Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.")
        if not hmac.compare_digest(g.parola.encode(), cfg.parola.encode()):
            q.append(simdi)
            await asyncio.sleep(1.0)
            raise HTTPException(401, "Parola yanlış")
        q.clear()
        t = secrets.token_urlsafe(32)
        oturumlar[t] = simdi + OTURUM_SURE
        resp.set_cookie(CEREZ, t, max_age=OTURUM_SURE, httponly=True, samesite="strict", secure=cfg.guvenli_cerez, path="/")
        return {"tamam": True}

    @app.post("/api/cikis")
    async def cikis(req: Request, resp: Response):
        oturumlar.pop(req.cookies.get(CEREZ, ""), None)
        resp.delete_cookie(CEREZ, path="/")
        return {"tamam": True}

    # ---------------------------------------------------------- durum / sinyaller
    @app.get("/api/durum")
    async def durum():
        return _temiz({"durum": tarayici.durum_ozet(), "uyari": UYARI, "param": tarayici.p.ozet(),
                       "param_surum": tarayici.p.surum, "kaynak": tarayici.borsa.ad,
                       "simdi": tarayici.borsa.simdi_ms() / 1000, "hatali": tarayici.durum.get("hatali", {})})

    @app.get("/api/sinyaller")
    async def sinyaller():
        return _temiz({"aktif": tarayici.aktif, "yaklasan": tarayici.yaklasan, "tetik_tf": tarayici.p.tetik_tf,
                       "param": tarayici.p.ozet(), "evren": tarayici.evren, "durum": tarayici.durum_ozet()})

    @app.get("/api/mumlar")
    async def mumlar(sembol: str = Query(..., max_length=30), aralik: Literal["1h", "4h"] = "1h",
                     limit: int = Query(500, ge=50, le=3000)):
        try:
            s = veri.sembol_dogrula(sembol)
        except ValueError as e:
            raise HTTPException(400, str(e))
        df = tarayici.mumlar.get(s)
        if df is None:
            try:
                df = await asyncio.to_thread(tarayici.borsa.mumlar, s, "1h", None, cfg.gecmis_mum)
            except Exception as e:
                raise HTTPException(502, f"veri alınamadı: {type(e).__name__}")
        if df is None or len(df) < 50:
            raise HTTPException(404, "sembol verisi yok")
        p = tarayici.p
        h = tarayici.hazir.get(s)
        if h is None:
            h = await asyncio.to_thread(tarayici.hazirla_sembol, df, None, s)
        if aralik == p.tetik_tf:
            g = h.iloc[-limit:]  # strateji görünümü: kanal + sinyal işaretleri
        else:
            g = veri.yeniden_ornekle(df, aralik) if aralik != "1h" else df.copy()
            if aralik == p.rejim_tf:
                g["ema_r"] = ema(g["close"], p.ema_n)
            else:
                g["ema_r"] = rejim_hizala(df, "1h", p.rejim_tf, p.ema_n)["ema_r"]
            g["kanal_ust"] = np.nan
            g["kanal_alt"] = np.nan
            g = g.iloc[-limit:]
        t = (g.index.as_unit("s").asi8).tolist()

        def seri(col):
            return [[ti, float(v)] for ti, v in zip(t, g[col].to_numpy(float)) if math.isfinite(v)]
        isaret = []
        if aralik == p.tetik_tf:
            for ti, l_, s_ in zip(t, g["long_yeni"].to_numpy(bool), g["short_yeni"].to_numpy(bool)):
                if l_:
                    isaret.append({"t": ti, "yon": "LONG"})
                elif s_:
                    isaret.append({"t": ti, "yon": "SHORT"})
        ohlc = [[ti, *map(float, r)] for ti, r in zip(t, g[["open", "high", "low", "close"]].to_numpy(float))]
        return _temiz({"sembol": s, "aralik": aralik, "mumlar": ohlc, "ema": seri("ema_r"),
                       "kanal_ust": seri("kanal_ust"), "kanal_alt": seri("kanal_alt"), "isaretler": isaret,
                       "ema_n": p.ema_n, "giris_n": p.giris_n, "atr": float(h["atr"].iloc[-1]), "tetik_tf": p.tetik_tf,
                       "rejim_tf": p.rejim_tf,
                       "aktif": [x for x in tarayici.aktif + tarayici.yaklasan if x["sembol"] == s]})

    # ---------------------------------------------------------- piyasa bağlamı ve türev verileri
    from .piyasa import PiyasaBaglami
    from . import turev as _turev

    piyasa = PiyasaBaglami()
    turev_onbellek: dict[str, tuple[float, dict]] = {}

    @app.get("/api/piyasa")
    async def piyasa_ozet(n: int = Query(100, ge=10, le=250)):
        ozet = await asyncio.to_thread(piyasa.ozet)
        harita = await asyncio.to_thread(piyasa.cg.isi_haritasi, n)
        kaynak = "CoinGecko"
        if not harita:  # CoinGecko yoksa: izlenen Binance vadeli sembollerinden kendi ısı haritamız
            kaynak = "Binance vadeli (izlenen semboller)"
            for e in tarayici.evren:
                df = tarayici.mumlar.get(e["sembol"])
                if df is None or len(df) < 170:
                    continue
                c = df["close"]
                harita.append({"sembol": e["sembol"].removesuffix("USDT"), "ad": e["sembol"], "fiyat": float(c.iloc[-1]),
                               "piyasa_degeri": e["hacim24"], "hacim": e["hacim24"],
                               "d1s": float(c.iloc[-1] / c.iloc[-2] - 1) * 100, "d24s": float(c.iloc[-1] / c.iloc[-25] - 1) * 100,
                               "d7g": float(c.iloc[-1] / c.iloc[-169] - 1) * 100, "stabil": False})
        vadeli = {e["sembol"].removesuffix("USDT") for e in tarayici.evren}
        for h in harita:
            h["vadeli"] = h["sembol"] in vadeli
        return _temiz({**ozet, "isi_haritasi": harita, "harita_kaynak": kaynak})

    @app.get("/api/turev")
    async def turev_veri(sembol: str = Query(..., max_length=30)):
        try:
            s = veri.sembol_dogrula(sembol)
        except ValueError as e:
            raise HTTPException(400, str(e))
        kayit = turev_onbellek.get(s)
        if kayit and time.time() - kayit[0] < 300:
            return kayit[1]
        try:
            m = await asyncio.to_thread(tarayici.borsa.metrik, s)
        except Exception as e:
            raise HTTPException(502, f"türev verisi alınamadı: {type(e).__name__}")
        if m is None or m.empty:
            return {"sembol": s, "veri": None}
        tf = tarayici.p.tetik_tf
        idx = (m.index if tf == "1h" else m.resample(tf, label="left", closed="left", origin="epoch").last().index)
        o = _turev.ozellikler(m, None, idx, tf, oi_n=tarayici.p.oi_n, z_n=min(180, max(20, len(idx) - 1)))
        son = o.dropna(subset=["oi"]).iloc[-1] if o["oi"].notna().any() else None
        try:
            f = await asyncio.to_thread(tarayici.borsa.fonlama, s)
            fonlama = float(f.iloc[-1]) if len(f) else None
        except Exception:
            fonlama = None
        cevap = _temiz({"sembol": s, "zaman": son.name.isoformat() if son is not None else None, "tf": tf,
                        "veri": None if son is None else {k: (float(son[k]) if pd.notna(son[k]) else None)
                                                          for k in ("oi", "oi_deg", "ls_hesap", "ls_z", "top_ls", "taker")},
                        "fonlama": fonlama, "seri_oi": [[int(t.timestamp()), float(v)] for t, v in m["oi"].dropna().iloc[-500:].items()],
                        "kaynak": "Binance herkese açık futures/data (CoinGlass'taki Binance verisiyle aynı ham veri)"})
        turev_onbellek[s] = (time.time(), cevap)
        return cevap

    # ---------------------------------------------------------- pozisyonlar
    @app.get("/api/pozisyonlar")
    async def pozisyonlar():
        return _temiz({"pozisyonlar": db.pozisyonlar()})

    @app.post("/api/pozisyonlar")
    async def pozisyon_ekle(p: PozisyonIstek):
        adet = p.adet or ((p.notional or 0) / p.giris)
        if adet <= 0:
            raise HTTPException(400, "miktar veya pozisyon $ girin")
        yon = 1 if p.yon == "LONG" else -1
        if (p.giris - p.stop) * yon <= 0:
            raise HTTPException(400, "Stop, LONG'da girişin altında, SHORT'ta üstünde olmalı")
        pid = db.pozisyon_ekle({"sembol": p.sembol, "yon": p.yon, "giris": p.giris, "adet": adet, "kaldirac": p.kaldirac,
                                "stop": p.stop, "acilis": pd.Timestamp.now(tz="UTC").isoformat() if tarayici.borsa.canli
                                else pd.Timestamp(tarayici.borsa.simdi_ms(), unit="ms", tz="UTC").isoformat(),
                                "sinyal_id": p.sinyal_id, "not_metni": p.not_metni})
        poz = db.pozisyon(pid)
        h = tarayici.hazir.get(p.sembol)
        d = tarayici.pozisyon_degerlendir(poz, h)
        d.pop("_stop_degisti", None)
        d.pop("_zaman", None)
        db.pozisyon_guncelle(pid, d)
        if h is None and p.sembol not in tarayici.mumlar:
            asyncio.create_task(tarayici.tara())  # yeni sembolü izlemeye al
        return _temiz({"id": pid, "pozisyon": db.pozisyon(pid)})

    @app.patch("/api/pozisyonlar/{pid}")
    async def pozisyon_guncelle(pid: int, g: PozisyonGuncelle):
        poz = db.pozisyon(pid)
        if not poz:
            raise HTTPException(404, "yok")
        d = {k: v for k, v in g.model_dump().items() if v is not None}
        if "stop" in d:
            yon = 1 if poz["yon"] == "LONG" else -1
            son = poz.get("son_fiyat") or poz["giris"]
            if (son - d["stop"]) * yon <= 0:
                raise HTTPException(400, "Stop mevcut fiyatın yanlış tarafında")
        db.pozisyon_guncelle(pid, d)
        poz = db.pozisyon(pid)
        e = tarayici.pozisyon_degerlendir(poz, tarayici.hazir.get(poz["sembol"]))
        e.pop("_stop_degisti", None)
        e.pop("_zaman", None)
        db.pozisyon_guncelle(pid, e)
        return _temiz({"pozisyon": db.pozisyon(pid)})

    @app.post("/api/pozisyonlar/{pid}/kapat")
    async def pozisyon_kapat(pid: int, k: KapatIstek):
        poz = db.pozisyon(pid)
        if not poz or poz["durum"] != "acik":
            raise HTTPException(404, "açık pozisyon yok")
        yon = 1 if poz["yon"] == "LONG" else -1
        pnl = yon * poz["adet"] * (k.fiyat - poz["giris"])
        risk = abs(poz["giris"] - (poz["ilk_stop"] or poz["stop"])) * poz["adet"]
        db.pozisyon_guncelle(pid, {"durum": "kapali", "kapanis": pd.Timestamp.now(tz="UTC").isoformat(),
                                   "kapanis_fiyat": k.fiyat, "pnl": pnl, "r": pnl / risk if risk else None})
        return _temiz({"pozisyon": db.pozisyon(pid)})

    @app.delete("/api/pozisyonlar/{pid}")
    async def pozisyon_sil(pid: int):
        db.pozisyon_sil(pid)
        return {"tamam": True}

    # ---------------------------------------------------------- geçmiş
    def _bt_beklenti() -> dict | None:
        """Canlı parametrelerle AYNI sürümdeki backtest varyantının beklentisi (yoksa temel + uyarı)."""
        yol = rapor_yolu()
        if not yol.exists():
            return None
        try:
            rp = json.loads(yol.read_text())
            ad = next((k for k, x in rp["varyantlar"].items() if x.get("surum") == tarayici.p.surum), None)
            ty = yol.parent / "turev.json"
            if ad is None and ty.exists():  # türev filtreli varyantlar ayrı deneyde (2022+)
                tr = json.loads(ty.read_text())
                for tad, x in tr["tabanlar"].items():
                    for fad, f in x["filtreler"].items():
                        if f.get("surum") == tarayici.p.surum:
                            return {"kaynak": rp["olusturma"], "demo": rp.get("demo"), "surum": f["surum"],
                                    "varyant": f"{tad} {fad} (2022+)", "eslesme": True, "genel": f["r"],
                                    "long": None, "short": None, "holdout": f["holdout"]}
            v = rp["varyantlar"][ad or "temel"]
            o = v["ozet"]
            return {"kaynak": rp["olusturma"], "demo": rp.get("demo"), "surum": v.get("surum"), "varyant": ad or "temel",
                    "eslesme": ad is not None,
                    "genel": o["havuz_r"], "long": o.get("long_r"), "short": o.get("short_r"),
                    "holdout": v.get("holdout")}
        except Exception:
            return None

    @app.get("/api/gecmis")
    async def gecmis(limit: int = Query(500, ge=1, le=5000)):
        s = db.sinyaller(limit)
        semb: dict[str, list] = defaultdict(list)
        for x in s:
            semb[x["sembol"]].append(x)
        return _temiz({"sinyaller": s, "istatistik": {
            "genel": istatistik(s), "long": istatistik([x for x in s if x["yon"] == "LONG"]),
            "short": istatistik([x for x in s if x["yon"] == "SHORT"]),
            "yeni": istatistik([x for x in s if x["yeni"]]),
            "sembol": {k: istatistik(v) for k, v in sorted(semb.items())}},
            "backtest": _bt_beklenti(), "param_surum": tarayici.p.surum})

    # ---------------------------------------------------------- backtest
    @app.get("/api/backtest")
    async def backtest():
        yol = rapor_yolu()
        if not yol.exists():
            return {"rapor": None, "calisma": bt_durum}
        ty = yol.parent / "turev.json"
        turev_b = ty.read_bytes() if ty.exists() else b"null"
        return Response(content=b'{"calisma":' + json.dumps(bt_durum).encode() + b',"turev":' + turev_b + b',"rapor":' + yol.read_bytes() + b"}",
                        media_type="application/json")

    @app.post("/api/backtest/calistir")
    async def backtest_calistir(b: BacktestIstek):
        if bt_durum.get("calisiyor"):
            raise HTTPException(409, "zaten çalışıyor")
        komut = [sys.executable, str(KOK / "tarayici.py"), "backtest"] + (["--hizli"] if b.hizli else [])
        if not tarayici.borsa.canli and not (veri.VARSAYILAN_ONBELLEK / "BTCUSDT_1h.csv").exists():
            komut.append("--demo")
        bt_durum.update(calisiyor=True, baslangic=time.time(), son_satir="başlatıldı", kod=None)

        async def izle():
            proc = await asyncio.create_subprocess_exec(*komut, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL, cwd=str(KOK))
            logyol = KOK / "loglar" / "backtest.log"
            while proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    pass
                if logyol.exists():
                    with logyol.open("rb") as f:
                        f.seek(max(0, logyol.stat().st_size - 400))
                        bt_durum["son_satir"] = f.read().decode(errors="ignore").strip().splitlines()[-1][-200:]
            bt_durum.update(calisiyor=False, kod=proc.returncode, bitis=time.time())
            tarayici.yayinci.yayinla("backtest", bt_durum)

        asyncio.create_task(izle())
        return bt_durum

    # ---------------------------------------------------------- ileri test (DENEYLER.md §3)
    it_durum: dict = {"calisiyor": False}
    it_yol = RAPOR_DIZINI / "ileri_test.json"

    async def ileri_test_baslat() -> dict:
        if it_durum.get("calisiyor"):
            raise HTTPException(409, "zaten çalışıyor")
        it_durum.update(calisiyor=True, baslangic=time.time(), kod=None)

        async def izle():
            proc = await asyncio.create_subprocess_exec(sys.executable, str(KOK / "tarayici.py"), "ileri-test",
                                                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                        cwd=str(KOK))
            await proc.wait()
            it_durum.update(calisiyor=False, kod=proc.returncode, bitis=time.time())
            tarayici.yayinci.yayinla("ileri_test", it_durum)

        asyncio.create_task(izle())
        return it_durum

    @app.get("/api/ileri-test")
    async def ileri_test_al():
        rp = it_yol.read_bytes() if it_yol.exists() else b"null"
        return Response(content=b'{"calisma":' + json.dumps(it_durum).encode() + b',"rapor":' + rp + b"}",
                        media_type="application/json")

    @app.post("/api/ileri-test/calistir")
    async def ileri_test_calistir():
        if not tarayici.borsa.canli and not (veri.VARSAYILAN_ONBELLEK / "BTCUSDT_1h.csv").exists():
            raise HTTPException(400, "demo modunda arşiv önbelleği yok")
        return await ileri_test_baslat()

    async def ileri_test_gunluk():
        """Binance arşivi günlük dosyaları ertesi gün ~01-02 UTC'de yayınlar: her gün 03 UTC'den sonra bir kez güncelle."""
        while True:
            try:
                simdi = time.gmtime()
                bugun = time.strftime("%Y-%m-%d", simdi)
                son = json.loads(it_yol.read_text()).get("olusturma", "")[:10] if it_yol.exists() else ""
                if tarayici.borsa.canli and simdi.tm_hour >= 3 and son != bugun and not it_durum.get("calisiyor"):
                    await ileri_test_baslat()
            except Exception as e:  # sessizce sonraki saate
                log.warning("ileri test otomatik güncelleme: %s", e)
            await asyncio.sleep(3600)

    @app.on_event("startup")
    async def _ileri_test_zamanla():
        asyncio.create_task(ileri_test_gunluk())

    # ---------------------------------------------------------- ayarlar
    @app.get("/api/ayarlar")
    async def ayarlar_al():
        return {k: getattr(cfg, k) for k in A.DEGISEBILIR} | {
            "telegram_hazir": bool(cfg.tg_token and cfg.tg_chat), "push_anahtar": _vapid_acik(),
            "parola_var": bool(cfg.parola), "host": cfg.host}

    @app.post("/api/ayarlar")
    async def ayarlar_yaz(d: dict):
        try:
            temiz = A.dogrula(d)
        except ValueError as e:
            raise HTTPException(400, str(e))
        db.ayar_yaz(temiz)
        for k, v in temiz.items():
            setattr(cfg, k, v)
        if "sembol_sayisi" in temiz:
            tarayici.evren_zaman = 0  # sonraki taramada evreni yenile
        return {"tamam": True, "not": "Değişiklikler sonraki taramada devreye girer."}

    def _vapid_acik() -> str | None:
        import os
        return os.environ.get("VAPID_PUBLIC_KEY") or None

    @app.get("/api/telefon")
    async def telefon_bilgi(req: Request):
        from . import telefon as tel

        host = req.headers.get("host", "")
        url = cfg.telefon_url or (f"https://{host}" if host.endswith(".ts.net") else None)
        sonuc = getattr(cfg, "telefon_sonuc", None) or {}
        return {"url": url, "qr_svg": tel.qr_svg(url) if url else None, "mesaj": sonuc.get("mesaj"),
                "onay_url": sonuc.get("onay_url"), "indir": tel.INDIR}

    @app.post("/api/push/abone")
    async def push_abone(p: PushIstek):
        db.push_ekle(p.model_dump())
        return {"tamam": True}

    # ---------------------------------------------------------- canlı olaylar (SSE)
    @app.get("/api/olaylar")
    async def olaylar(req: Request):
        q = tarayici.yayinci.abone()

        async def akis():
            try:
                yield f"event: merhaba\ndata: {json.dumps(_temiz(tarayici.durum_ozet()))}\n\n"
                while True:
                    if await req.is_disconnected():
                        break
                    try:
                        olay, veri_ = await asyncio.wait_for(q.get(), 15)
                        yield f"event: {olay}\ndata: {json.dumps(_temiz(veri_), default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield f"event: nabiz\ndata: {json.dumps({'t': time.time()})}\n\n"
            finally:
                tarayici.yayinci.ayril(q)

        return StreamingResponse(akis(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------- statik (PWA)
    @app.get("/")
    async def kok():
        return FileResponse(STATIK / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    async def sw():
        return FileResponse(STATIK / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.json")
    async def manifest():
        return FileResponse(STATIK / "manifest.json", media_type="application/manifest+json")

    # Bu modüller telefon uygulamasıyla ORTAK dosyalardır (depo kökü); masaüstü aynı dosyaları sunar.
    MOBIL = KOK.parent

    def _ortak(ad: str):
        async def sun():
            yol = MOBIL / ad
            if not yol.exists():
                raise HTTPException(404)
            tur = "application/javascript" if ad.endswith(".js") else "application/json"
            return FileResponse(yol, media_type=tur, headers={"Cache-Control": "no-cache"})
        return sun

    for _ad in ("tema.js", "tarama.js", "tarama_baslat.js", "tarama_istatistik.json", "analiz.js", "formasyon.js", "strateji.js",
                "formasyon_istatistik.json", "meta.js", "meta_model.json"):
        app.add_api_route(f"/static/{_ad}", _ortak(_ad), methods=["GET"])

    app.mount("/static", StaticFiles(directory=STATIK), name="static")
    return app
