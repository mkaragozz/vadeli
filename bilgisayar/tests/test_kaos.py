"""Kaos özellikleri (DENEYLER.md §10): Hurst ve permütasyon entropisi doğru ölçer ve geleceğe bakmaz."""
import numpy as np
import pandas as pd

from vadeli import meta


def _seriler(n=4000):
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, n)
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = 0.6 * e[i - 1] + r[i]
    return (pd.Series(np.exp(np.cumsum(r))), pd.Series(np.exp(np.cumsum(e))),
            pd.Series(np.exp(np.cumsum(r - np.r_[0, r[:-1]] * 0.6))))


def test_hurst_kalibrasyon():
    rw, tr, mr = _seriler()
    h = [meta.hurst(s).iloc[300:].mean() for s in (rw, tr, mr)]
    assert 0.44 < h[0] < 0.54 and h[1] > 0.65 and h[2] < 0.3


def test_entropi_sinirlar():
    rw, _, _ = _seriler()
    assert meta.perm_entropi(rw).iloc[300:].mean() > 0.9
    assert meta.perm_entropi(pd.Series(np.arange(1, 400, dtype=float))).iloc[-1] < 1e-9


def test_gelecege_bakmaz():
    rw, _, _ = _seriler()
    c2 = rw.copy()
    c2.iloc[1500:] *= 3
    pd.testing.assert_series_equal(meta.hurst(rw).iloc[:1500], meta.hurst(c2).iloc[:1500])
    pd.testing.assert_series_equal(meta.perm_entropi(rw).iloc[:1500], meta.perm_entropi(c2).iloc[:1500])
