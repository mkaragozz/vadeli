"""Türev konumlanma verileri: zaman hizalaması ve look-ahead testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vadeli import turev, veri
from vadeli.strateji import StratejiParam, hazirla


def _bes_dk(n_saat=400, tohum=0):
    rng = np.random.default_rng(tohum)
    idx = pd.date_range("2024-01-01", periods=n_saat * 12, freq="5min", tz="UTC")
    return pd.DataFrame({"oi": 1e9 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx)))),
                         "top_ls": rng.uniform(0.8, 1.5, len(idx)), "top_hesap_ls": rng.uniform(0.8, 1.5, len(idx)),
                         "ls_hesap": rng.uniform(0.5, 3, len(idx)), "taker_oran": rng.uniform(0.5, 1.5, len(idx))}, index=idx)


def test_saatlik_mum_kapanisindan_once_bilinen_veri():
    t = _bes_dk(10)
    s = turev.saatlige(t)
    # 01:00 mumu: 01:00..01:55 görüntüleri; son değer 01:55 (mum kapanışı 02:00'dan önce)
    assert s.loc["2024-01-01 01:00", "oi"] == t.loc["2024-01-01 01:55", "oi"]
    assert s.loc["2024-01-01 01:00", "taker_oran"] == pytest.approx(t.loc["2024-01-01 01:00":"2024-01-01 01:55", "taker_oran"].mean())


def test_gelecek_metrik_degisince_gecmis_ozellik_ayni():
    t = _bes_dk(400)
    idx = pd.date_range("2024-01-01", periods=400, freq="1h", tz="UTC")
    a = turev.ozellikler(turev.saatlige(t), None, idx, "1h")
    b_t = t.copy()
    b_t.loc["2024-01-10 00:00":, :] *= 3
    b = turev.ozellikler(turev.saatlige(b_t), None, idx, "1h")
    kes = idx.get_loc(pd.Timestamp("2024-01-10", tz="UTC"))
    pd.testing.assert_frame_equal(a.iloc[:kes], b.iloc[:kes])


def test_4s_ozellik_son_saati_kullanir():
    t = _bes_dk(48)
    s = turev.saatlige(t)
    idx4 = pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC")
    o = turev.ozellikler(s, None, idx4, "4h", oi_n=1)
    # 00:00-04:00 4s mumu: son görüntü 03:55
    assert o.loc[idx4[0], "oi"] == t.loc["2024-01-01 03:55", "oi"]


def test_fonlama_kapanista_bilinen():
    idx = pd.date_range("2024-01-01 05:00", periods=6, freq="1h", tz="UTC")
    f = pd.Series([0.001, 0.002], index=pd.to_datetime(["2024-01-01 00:00", "2024-01-01 08:00"], utc=True))
    o = turev.ozellikler(None, f, idx, "1h")
    # 07:00 mumu 08:00'de kapanır → 08:00 fonlaması bilinir; 06:00 mumu bilmez
    assert o.loc[idx[1], "fonlama"] == 0.001 and o.loc[idx[2], "fonlama"] == 0.002


def test_filtreler_sinyali_yalniz_azaltir():
    df = veri.rastgele_yuruyus(4000, tohum=5, surukleme=0.0003)
    t = _bes_dk(4000, tohum=1)
    t.index = pd.date_range(df.index[0], periods=len(t), freq="5min")
    ek = turev.ozellikler(turev.saatlige(t), None, df.index, "1h")
    taban = hazirla(df, StratejiParam(), ek=ek)
    for kw in ({"oi_teyit": True}, {"kalabalik_z": 1.0}, {"taker_teyit": True}, {"fonlama_esik": 0.0005}):
        h = hazirla(df, StratejiParam(**kw), ek=ek)
        assert (h["long_sinyal"] <= taban["long_sinyal"]).all() and (h["short_sinyal"] <= taban["short_sinyal"]).all()
    with pytest.raises(ValueError):
        hazirla(df, StratejiParam(oi_teyit=True))  # veri yoksa sessizce geçmez


def test_surum_eski_varyantlarda_degismedi():
    assert StratejiParam().surum == "p5c3736f3"


def test_canli_turev_filtresi_backtest_ile_ayni(tmp_path):
    """Canlı tarayıcı (yalnız son ~41 saatlik metrik) ile backtest (tam arşiv) son mumda aynı sinyali üretir."""
    import asyncio

    from tests.test_canli_pano import SentetikBorsa
    from vadeli.ayarlar import Ayarlar
    from vadeli.canli import Tarayici
    from vadeli.db import DB

    borsa = SentetikBorsa()
    tam_metrik = {}
    for s, df in borsa.veri.items():
        t = _bes_dk(len(df), tohum=hash(s) % 1000)
        t.index = pd.date_range(df.index[0], periods=len(t), freq="5min")
        tam_metrik[s] = turev.saatlige(t)

    def metrik(sembol, alanlar=None):
        sinir = pd.Timestamp(borsa.simdi_ms(), unit="ms", tz="UTC").floor("h")
        m = tam_metrik[sembol]
        return m[m.index < sinir].iloc[-41:]  # REST gibi kısa geçmiş
    borsa.metrik = metrik

    cfg = Ayarlar(veritabani=str(tmp_path / "t.db"), sinyal_csv=str(tmp_path / "s.csv"), websocket=False, sembol_sayisi=4,
                  tetik_tf="4h", rejim_tf="4h", btc_filtre=False, oi_teyit=True)
    tr = Tarayici(cfg, DB(cfg.veritabani), borsa)

    async def calis():
        await tr.evren_guncelle(zorla=True)
        for _ in range(9):
            await tr.tara()
            await borsa.sonraki_kapanisi_bekle(0)
    asyncio.run(calis())
    for s, h in tr.hazir.items():
        df = tr.mumlar[s]
        d4 = veri.yeniden_ornekle(df, "4h")
        ek = turev.ozellikler(tam_metrik[s], None, d4.index, "4h", oi_n=6)
        b = hazirla(d4, tr.p, ek=ek)
        son = h.index[-1]
        for c in ("oi_deg", "long_sinyal", "short_sinyal"):
            assert (h.loc[son, c] == b.loc[son, c]) or (pd.isna(h.loc[son, c]) and pd.isna(b.loc[son, c])), (s, c)
