"""Formasyon/sinyal araştırması: look-ahead yok, sonuç ölçümü doğru."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vadeli import formasyon as F
from vadeli import veri


@pytest.fixture(scope="module")
def df():
    return veri.rastgele_yuruyus(3000, tohum=8, surukleme=0.0002)


def test_sinyaller_gelecekten_etkilenmez(df):
    s1 = F.sinyaller(df)
    for kes in (1200, 2100):
        bozuk = df.copy()
        bozuk.iloc[kes + 1:, :4] *= 1.4
        bozuk.iloc[kes + 1:, 1] *= 1.05
        s2 = F.sinyaller(bozuk)
        for ad in s1:
            for k in (0, 1):
                assert (s1[ad][k][: kes + 1] == s2[ad][k][: kes + 1]).all(), (ad, k, kes)


def test_kesik_veri_son_mum_ayni(df):
    tam = F.sinyaller(df)
    for kes in (900, 1777, 2500):
        k = F.sinyaller(df.iloc[: kes + 1])
        for ad in tam:
            for y in (0, 1):
                assert k[ad][y][-1] == tam[ad][y][kes], (ad, y, kes)


def test_hepsi_bir_kez_sinyal_uretir(df):
    s = F.sinyaller(veri.rastgele_yuruyus(20000, tohum=2))
    bos = [ad for ad, (l, h) in s.items() if l.sum() + h.sum() == 0]
    assert not bos, bos


def _mum(o, h, l, c):
    idx = pd.date_range("2024-01-01", periods=len(o), freq="1h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1.0, "quote_volume": 1.0}, index=idx)


def test_sonuc_once_hedef_dogru():
    n = 40
    o = np.full(n, 100.0); h = o + 1; l = o - 1; c = o.copy()
    df = _mum(o, h, l, c)
    a = F.atr_hesap(df, 14).to_numpy()
    i = 30
    mesafe = F.STOP_ATR * a[i]
    h2 = h.copy(); h2[i + 2] = 100 + mesafe * 1.01     # 2. mumda hedef (k=1)
    durum, r = F.sonuclar(_mum(o, h2, l, c), 1, 1.0)
    assert durum[i] == 1
    assert r[i] == pytest.approx(1.0 - 2 * F.MALIYET * 100 / mesafe, rel=1e-6)


def test_ayni_mumda_ikisi_yanlis_sayilir():
    n = 40
    o = np.full(n, 100.0); h = o + 1; l = o - 1; c = o.copy()
    df = _mum(o, h, l, c)
    a = F.atr_hesap(df, 14).to_numpy()
    i = 30
    m = F.STOP_ATR * a[i]
    h2, l2 = h.copy(), l.copy()
    h2[i + 1] = 100 + 2 * m; l2[i + 1] = 100 - 2 * m
    durum, _ = F.sonuclar(_mum(o, h2, l2, c), 1, 1.0)
    assert durum[i] == 0


def test_hizalama_tamamlanmis_buyuk_mum():
    idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    b = pd.DataFrame(index=pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC"))
    deger = np.arange(12.0)
    x = F.hizala(idx, "1h", b, "4h", deger)
    assert np.isnan(x[0]) and np.isnan(x[2])
    assert x[3] == 0 and x[6] == 0 and x[7] == 1
