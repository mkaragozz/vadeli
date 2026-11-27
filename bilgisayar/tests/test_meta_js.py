"""Skor: telefon (mobil/meta.js) özellikleri ve LightGBM ağaç değerlendiricisi Python ile aynı sonucu verir."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vadeli import meta, veri

MOBIL = Path(__file__).resolve().parents[2]  # depo kökü
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node yok")


def _kopyala(tmp):
    for ad in ("meta.js", "formasyon.js", "strateji.js"):
        (tmp / ad).write_text((MOBIL / ad).read_text())


def _m(df):
    return {"t": (df.index.as_unit("ms").asi8).tolist(), "o": df["open"].tolist(), "h": df["high"].tolist(),
            "l": df["low"].tolist(), "c": df["close"].tolist(), "v": df["quote_volume"].tolist()}


@pytest.mark.parametrize("tf", ["4h", "1d"])
def test_ozellikler_ayni(tmp_path, tf):
    """Python tam geçmişle, JS son 500 mumla hesaplar (telefon 500 mum çeker): sonuç aynı olmalı."""
    h = veri.rastgele_yuruyus(24 * 2000, tohum=5, surukleme=0.0001)
    rng = np.random.default_rng(3)
    h["quote_volume"] *= rng.lognormal(0, 0.5, len(h))
    df = veri.yeniden_ornekle(h, tf)
    ust = veri.yeniden_ornekle(h, meta.UST_TF[tf])
    btc = veri.yeniden_ornekle(veri.rastgele_yuruyus(24 * 2000, tohum=6), tf)
    py = meta.ozellikler(df, ust, tf, btc).iloc[-1]
    _kopyala(tmp_path)
    son = df.iloc[-500:]
    (tmp_path / "g.json").write_text(json.dumps({"m": _m(son), "u": _m(ust.iloc[-300:]), "b": _m(btc.iloc[-500:]),
                                                 "tf": veri.ARALIK_MS[tf], "uf": veri.ARALIK_MS[meta.UST_TF[tf]]}))
    (tmp_path / "c.mjs").write_text("""
import { ozellikler } from './meta.js'; import fs from 'fs';
const g = JSON.parse(fs.readFileSync(new URL('./g.json', import.meta.url)));
const o = ozellikler(g.m, g.u, g.b, g.tf, g.uf);
console.log(JSON.stringify(Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Number.isNaN(v) ? null : v]))));
""")
    js = json.loads(subprocess.run(["node", str(tmp_path / "c.mjs")], capture_output=True, text=True, check=True).stdout)
    for k in meta.OZELLIK:
        a, b = py[k], js[k]
        if b is None:
            assert not np.isfinite(a), k
        else:
            assert a == pytest.approx(b, rel=1e-6, abs=1e-9), k


def test_agac_degerlendirici_ayni(tmp_path):
    import lightgbm as lgb

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(3000, 5)), columns=list("abcde"))
    X.loc[rng.random(3000) < 0.1, "c"] = np.nan
    y = ((X["a"] + np.nan_to_num(X["c"]) * 0.5 + rng.normal(size=3000) * 0.5) > 0).astype(int)
    m = lgb.LGBMClassifier(n_estimators=60, num_leaves=15, verbose=-1).fit(X, y)
    Xt = X.iloc[:200].copy()
    Xt.loc[Xt.index[::7], "a"] = np.nan   # eğitimde eksik görmemiş sütunda eksik değer (LightGBM: 0 sayar)
    py = m.predict_proba(Xt)[:, 1]
    _kopyala(tmp_path)
    (tmp_path / "g.json").write_text(json.dumps({"model": meta.agac_json(m, list(X.columns)),
                                                 "x": [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in Xt.to_dict("records")]}))
    (tmp_path / "c.mjs").write_text("""
import { agacTahmin } from './meta.js'; import fs from 'fs';
const g = JSON.parse(fs.readFileSync(new URL('./g.json', import.meta.url)));
console.log(JSON.stringify(g.x.map((r) => agacTahmin(g.model, Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v === null ? NaN : v]))))));
""")
    js = np.array(json.loads(subprocess.run(["node", str(tmp_path / "c.mjs")], capture_output=True, text=True, check=True).stdout))
    assert np.allclose(js, py, atol=1e-9)
