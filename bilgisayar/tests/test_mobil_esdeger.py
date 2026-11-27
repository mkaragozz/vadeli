"""Telefon sürümü (vadeli/strateji.js) ile Python stratejisinin AYNI veride AYNI sinyalleri ürettiğini kanıtlar."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vadeli import turev, veri
from vadeli.strateji import MaliyetParam, RiskParam, StratejiParam, hazirla, risk_hesapla

JS = Path(__file__).resolve().parents[2] / "strateji.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None or not JS.exists(), reason="node veya strateji.js yok")
P = StratejiParam(tetik_tf="4h", rejim_tf="4h", btc_filtre=True, oi_teyit=True, oi_n=6)
KOLON = ["rejim", "long_sinyal", "short_sinyal", "long_yeni", "short_yeni", "long_cikis", "short_cikis", "long_yakin", "short_yakin"]


def _js(tmp_path: Path, girdi: dict) -> dict:
    mod = tmp_path / "strateji.mjs"
    mod.write_text(JS.read_text())
    (tmp_path / "girdi.json").write_text(json.dumps(girdi))
    betik = tmp_path / "calistir.mjs"
    betik.write_text("""
import * as S from './strateji.mjs';
import fs from 'fs';
const g = JSON.parse(fs.readFileSync(new URL('./girdi.json', import.meta.url)));
const p = { ...S.VARSAYILAN };
const btcSatir = S.hazirla(g.btc, { ...p, btc_filtre: false, oi_teyit: false });
const btc = new Map(btcSatir.map((x) => [x.t, x.rejim]));
const oi = S.oiHizala(g.m.t, g.oi, '4h');
const s = S.hazirla(g.m, p, btc, oi);
const nz = (x) => (Number.isNaN(x) ? null : x);
const r = { hesap: 1000, risk_yuzde: 1, max_kaldirac: 5 };
console.log(JSON.stringify({ satir: s.map((x) => ({ ...x, atr: nz(x.atr), ema: nz(x.ema), oi_deg: nz(x.oi_deg) })),
  risk: [S.riskHesapla(100, 97, 1, r), S.riskHesapla(100, 90, -1, r), S.riskHesapla(2.5, 2.49, 1, r)] }));
""")
    cikti = subprocess.run(["node", str(betik)], capture_output=True, text=True, check=True).stdout
    return json.loads(cikti)


def _girdi(df4: pd.DataFrame, btc4: pd.DataFrame, oi_1h: pd.DataFrame) -> dict:
    def mumlar(d):
        return {"t": (d.index.as_unit("ms").asi8).tolist(), "o": d["open"].tolist(), "h": d["high"].tolist(),
                "l": d["low"].tolist(), "c": d["close"].tolist()}
    oi = [[int(t), float(v)] for t, v in zip(oi_1h.index.as_unit("ms").asi8, oi_1h["oi"]) if np.isfinite(v)]
    return {"m": mumlar(df4), "btc": mumlar(btc4), "oi": oi}


def _python(df4, btc4, oi_1h):
    sade = replace(P, btc_filtre=False, oi_teyit=False)
    btc = hazirla(btc4, sade)["rejim"]
    ek = turev.ozellikler(oi_1h, None, df4.index, "4h", oi_n=P.oi_n)
    return hazirla(df4, P, btc, ek)


def _karsilastir(py: pd.DataFrame, js: dict) -> None:
    js_df = pd.DataFrame(js["satir"])
    assert len(js_df) == len(py)
    for c in KOLON:
        farkli = np.flatnonzero(py[c].to_numpy() != js_df[c].to_numpy())
        assert len(farkli) == 0, (c, farkli[:5], py.index[farkli[:5]].tolist())
    for c, jc in (("atr", "atr"), ("ema_r", "ema"), ("kanal_ust", "kanal_ust"), ("cikis_alt", "cikis_alt"), ("oi_deg", "oi_deg")):
        a = py[c].to_numpy(float)
        b = js_df[jc].to_numpy(float)
        assert np.allclose(a, b, rtol=1e-9, equal_nan=True), c
    assert py["long_sinyal"].sum() + py["short_sinyal"].sum() > 0, "testte hiç sinyal yok (anlamsız test)"


def test_sentetik_veride_ayni(tmp_path):
    df = veri.rastgele_yuruyus(12_000, tohum=11, surukleme=0.0003)
    btc = veri.rastgele_yuruyus(12_000, tohum=12, surukleme=0.0002)
    rng = np.random.default_rng(3)
    oi_1h = pd.DataFrame({"oi": 1e9 * np.exp(np.cumsum(rng.normal(0, 0.01, len(df))))}, index=df.index)
    oi_1h.iloc[500:520] = np.nan  # veri boşluğu
    df4, btc4 = veri.yeniden_ornekle(df, "4h"), veri.yeniden_ornekle(btc, "4h")
    js = _js(tmp_path, _girdi(df4, btc4, oi_1h))
    _karsilastir(_python(df4, btc4, oi_1h), js)
    m = MaliyetParam()
    for jr, (g, s, y) in zip(js["risk"], ((100, 97, 1), (100, 90, -1), (2.5, 2.49, 1))):
        pr = risk_hesapla(g, s, y, RiskParam(), m)
        for k in ("kaldirac", "notional", "teminat", "likidasyon", "risk_usdt"):
            assert jr[k] == pytest.approx(pr[k], rel=1e-12), k


@pytest.mark.parametrize("sembol", ["ETHUSDT", "SOLUSDT"])
def test_gercek_veride_ayni(tmp_path, sembol):
    o = veri.VARSAYILAN_ONBELLEK
    if not all((o / f).exists() for f in (f"{sembol}_1h.csv", "BTCUSDT_1h.csv", f"{sembol}_metrik_1h.csv")):
        pytest.skip("arşiv önbelleği yok")
    df = veri._csv_oku(o / f"{sembol}_1h.csv").loc["2023-01-01":]
    btc = veri._csv_oku(o / "BTCUSDT_1h.csv").loc["2023-01-01":]
    oi_1h = veri._csv_oku(o / f"{sembol}_metrik_1h.csv")[["oi"]].loc["2023-01-01":]
    df4, btc4 = veri.yeniden_ornekle(df, "4h"), veri.yeniden_ornekle(btc, "4h")
    _karsilastir(_python(df4, btc4, oi_1h), _js(tmp_path, _girdi(df4, btc4, oi_1h)))


def test_surum_python_ile_ayni():
    assert f'SURUM = "{P.surum}"' in JS.read_text()
