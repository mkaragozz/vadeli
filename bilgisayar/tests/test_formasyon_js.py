"""Telefon/pano formasyon tespiti (mobil/formasyon.js) ile Python (vadeli/formasyon.py) aynı veride aynı sinyalleri verir."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vadeli import formasyon as F
from vadeli import veri

MOBIL = Path(__file__).resolve().parents[2]  # depo kökü
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node yok")


def _js(tmp_path: Path, df: pd.DataFrame, son_n: int) -> dict:
    for ad in ("formasyon.js", "strateji.js"):
        (tmp_path / ad).write_text((MOBIL / ad).read_text())
    m = {"o": df["open"].tolist(), "h": df["high"].tolist(), "l": df["low"].tolist(), "c": df["close"].tolist(),
         "v": df["quote_volume"].tolist()}
    (tmp_path / "girdi.json").write_text(json.dumps({"m": m, "son_n": son_n}))
    (tmp_path / "c.mjs").write_text("""
import * as F from './formasyon.js';
import fs from 'fs';
const g = JSON.parse(fs.readFileSync(new URL('./girdi.json', import.meta.url)));
const S = F.sinyaller(g.m);
const n = g.m.c.length, sev = [];
for (let i = n - g.son_n; i < n - 1; i++) for (const y of [1, -1]) {
  const s = F.seviyeHedefi(g.m, i, y, g.m.o[i + 1]); sev.push(s ? [s.hedef, s.stop] : null); }
console.log(JSON.stringify({ S, trend: F.trend(g.m.c), sev }));
""")
    return json.loads(subprocess.run(["node", str(tmp_path / "c.mjs")], capture_output=True, text=True, check=True).stdout)


def _karsilastir(tmp_path, df):
    son_n = 60
    js = _js(tmp_path, df, son_n)
    py = F.sinyaller(df)
    toplam = 0
    for ad, (l, s) in py.items():
        jl, jsh = np.array(js["S"][ad][0]), np.array(js["S"][ad][1])
        for a, b, y in ((l, jl, "long"), (s, jsh, "short")):
            fark = np.flatnonzero(a != b)
            assert len(fark) == 0, (ad, y, fark[:5])
            toplam += int(a.sum())
    assert toplam > 50
    assert (F.trend(df) == np.array(js["trend"])).all()
    n = len(df)
    k = 0
    for yon in (1, -1):
        giris, stop, hedef = F.seviye_hedefleri(df, yon)
        for j, i in enumerate(range(n - son_n, n - 1)):
            x = js["sev"][2 * j + (0 if yon == 1 else 1)]
            if not np.isfinite(stop[i]):
                continue
            assert x[1] == pytest.approx(stop[i], rel=1e-9)
            if np.isfinite(hedef[i]):
                assert x[0] == pytest.approx(hedef[i], rel=1e-12)
                k += 1
            else:
                assert x[0] is None
    assert k > 0


def test_sentetik(tmp_path):
    df = veri.rastgele_yuruyus(4000, tohum=21, surukleme=0.0002)
    rng = np.random.default_rng(1)
    df["quote_volume"] *= rng.lognormal(0, 0.7, len(df))
    _karsilastir(tmp_path, df)


@pytest.mark.parametrize("sembol,tf", [("BTCUSDT", "4h"), ("SOLUSDT", "1d"), ("DOGEUSDT", "1h")])
def test_gercek(tmp_path, sembol, tf):
    yol = veri.VARSAYILAN_ONBELLEK / "spot" / f"{sembol}_1h.csv"
    if not yol.exists():
        pytest.skip("spot önbelleği yok")
    df = veri._csv_oku(yol)
    df = veri.yeniden_ornekle(df, tf) if tf != "1h" else df
    _karsilastir(tmp_path, df.iloc[-3000:])
