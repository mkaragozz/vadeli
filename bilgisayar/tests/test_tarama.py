"""Tarama: telefon/pano (mobil/tarama.js) ile Python (vadeli/tarama.py) ölçüleri aynı; look-ahead yok; varlık türleri."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vadeli import tarama, veri

JS = Path(__file__).resolve().parents[2] / "tarama.js"
node_yok = pytest.mark.skipif(shutil.which("node") is None, reason="node yok")


def _gunluk(n=500, tohum=4):
    g = veri.yeniden_ornekle(veri.rastgele_yuruyus(n * 24 + 24, tohum=tohum, surukleme=0.0002), "1d")
    rng = np.random.default_rng(tohum)
    g["quote_volume"] = g["quote_volume"] * rng.lognormal(0, 0.6, len(g))  # hacimde gerçekçi oynaklık
    return g


@node_yok
@pytest.mark.parametrize("n", [40, 120, 200, 500])
def test_js_python_ayni(tmp_path, n):
    g = _gunluk(n)
    (tmp_path / "tarama.mjs").write_text(JS.read_text())
    m = [[int(t), float(r.open), float(r.high), float(r.low), float(r.close), float(r.quote_volume)]
         for t, r in zip(g.index.as_unit("ms").asi8, g.itertuples())]
    (tmp_path / "girdi.json").write_text(json.dumps(m))
    (tmp_path / "c.mjs").write_text("""
import { olculer } from './tarama.mjs';
import fs from 'fs';
const m = JSON.parse(fs.readFileSync(new URL('./girdi.json', import.meta.url)));
console.log(JSON.stringify(olculer(m)));
""")
    js = json.loads(subprocess.run(["node", str(tmp_path / "c.mjs")], capture_output=True, text=True, check=True).stdout)
    py = tarama.olcu_serileri(g).iloc[-1]
    esle = {"g7": "g7", "g30": "g30", "g90": "g90", "g180": "g180", "g365": "g365", "hacim30": "hacim30",
            "hacim_egilim": "hacim_egilim", "hacim_patlama": "hacim_patlama", "hacim_kuruma": "hacim_kuruma", "zirveden": "zirveden"}
    for p, j in esle.items():
        a, b = py[p], js[j]
        if b is None:
            assert not np.isfinite(a), (p, a)
        else:
            assert a == pytest.approx(b, rel=1e-9), p


def test_olculer_gelecekten_etkilenmez():
    g = _gunluk(400)
    o1 = tarama.olcu_serileri(g)
    bozuk = g.copy()
    bozuk.iloc[301:, :] *= 3.0
    o2 = tarama.olcu_serileri(bozuk)
    pd.testing.assert_frame_equal(o1.iloc[:301], o2.iloc[:301])


def test_varlik_turu():
    duz = np.full(100, 1.0)
    oynak = np.linspace(1, 3, 100)
    assert tarama.varlik_turu("NVDAB", oynak) == "hisse"
    assert tarama.varlik_turu("BNB", oynak) == "kripto"
    assert tarama.varlik_turu("SHIB", oynak) == "kripto"
    assert tarama.varlik_turu("XAUT", oynak) == "emtia"
    assert tarama.varlik_turu("U", duz) == "stabil"


def test_sinif_kurali():
    o = pd.DataFrame({"hacim_patlama": [4.0, 1.0, 1.0], "hacim_egilim": [2.0, 2.0, 1.0], "hacim_kuruma": [1.0, 1.0, 0.2]})
    s = tarama.siniflar(o, tarama.VARSAYILAN_ESIK)
    assert s["patlama"].tolist() == [True, False, False]
    assert s["artan"].tolist() == [False, True, False]   # patlama olan ayrıca "artan" sayılmaz (JS ile aynı)
    assert s["kuruma"].tolist() == [False, False, True]
