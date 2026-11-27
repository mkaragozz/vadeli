"""Geliştirme turu 2 ve ileri test: göreli güç filtresi, başabaş stop, tek hesap portföyü, ileri test kuralları."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from vadeli import ileri_test, veri
from vadeli.backtest import PozisyonTakip
from vadeli.rapor_tur2 import tek_hesap
from vadeli.strateji import MaliyetParam, StratejiParam, hazirla

M0 = MaliyetParam(komisyon=0, kayma=0, fonlama_mod="yok")


@pytest.fixture(scope="module")
def iki_seri():
    a = veri.rastgele_yuruyus(4000, tohum=5, surukleme=0.0004)
    b = veri.rastgele_yuruyus(4000, tohum=6, surukleme=-0.0002)
    return a, b


def test_rs_gelecek_degisince_gecmis_ayni(iki_seri):
    coin, btc = iki_seri
    p = replace(StratejiParam(), rs_n=42)
    h1 = hazirla(coin, p, btc_kapanis=btc["close"])
    kes = 2500
    bozuk_btc = btc.copy()
    bozuk_btc.iloc[kes + 1:, :4] *= 0.5
    bozuk = coin.copy()
    bozuk.iloc[kes + 1:, :4] *= 1.6
    h2 = hazirla(bozuk, p, btc_kapanis=bozuk_btc["close"])
    pd.testing.assert_frame_equal(h1.iloc[: kes + 1], h2.iloc[: kes + 1], check_exact=False, rtol=1e-12)


def test_rs_filtre_yalniz_azaltir_ve_yonu_dogru(iki_seri):
    coin, btc = iki_seri
    t = hazirla(coin, StratejiParam())
    f = hazirla(coin, replace(StratejiParam(), rs_n=42), btc_kapanis=btc["close"])
    assert (f["long_sinyal"] <= t["long_sinyal"]).all() and (f["short_sinyal"] <= t["short_sinyal"]).all()
    assert (f.loc[f["long_sinyal"], "rs"] > 0).all()
    assert (f.loc[f["short_sinyal"], "rs"] < 0).all()


def test_rs_btc_icin_notr(iki_seri):
    coin, _ = iki_seri
    t = hazirla(coin, StratejiParam())
    f = hazirla(coin, replace(StratejiParam(), rs_n=42), btc_kapanis=None)
    assert (f["long_sinyal"] == t["long_sinyal"]).all()


def test_surum_yeni_alanlarla_degismedi():
    assert StratejiParam().surum == replace(StratejiParam(), rs_n=0, basabas_r=0.0).surum
    assert StratejiParam().surum != replace(StratejiParam(), rs_n=42).surum


def _poz(basabas: float) -> PozisyonTakip:
    return PozisyonTakip(yon=1, giris=100.0, adet=1.0, stop=90.0, likidasyon=50.0, teminat=20.0, risk_usdt=10.0,
                         kaldirac=5.0, giris_zaman=pd.Timestamp("2024-01-01", tz="UTC"), atr_kat=10.0,
                         maliyet=MaliyetParam(), basabas_r=basabas)


def test_basabas_stop_1R_sonra_girise_cekilir():
    p = _poz(1.0)
    p.kapanis_isle(105.0, 2.0, False, 0.0)       # +0.5R: stop yerinde (ATR takibi 85 < 90)
    assert p.stop == 90.0
    p.kapanis_isle(110.0, 2.0, False, 0.0)       # +1R: stop giriş + iki yön maliyet
    assert p.stop == pytest.approx(100.0 * (1 + 2 * MaliyetParam().tek_yon))
    p.kapanis_isle(104.0, 2.0, False, 0.0)       # geri çekilme: stop geri gitmez
    assert p.stop == pytest.approx(100.0 * (1 + 2 * MaliyetParam().tek_yon))


def test_basabas_kapaliyken_davranis_ayni():
    p = _poz(0.0)
    p.kapanis_isle(110.0, 2.0, False, 0.0)
    assert p.stop == 90.0


def test_tek_hesap_tavan_islemleri_atlar():
    t0 = pd.Timestamp("2024-01-01", tz="UTC")
    isl = pd.DataFrame({
        "giris_zaman": [t0, t0 + pd.Timedelta(hours=1), t0 + pd.Timedelta(hours=2), t0 + pd.Timedelta(days=5)],
        "cikis_zaman": [t0 + pd.Timedelta(days=3), t0 + pd.Timedelta(days=3), t0 + pd.Timedelta(days=3), t0 + pd.Timedelta(days=6)],
        "r": [1.0, -1.0, 2.0, 1.0]})
    tam = tek_hesap(isl, 0.01, None)
    iki = tek_hesap(isl, 0.01, 2)
    assert tam["islem"] == 4 and tam["atlanan"] == 0 and tam["max_eszamanli"] == 3
    assert iki["islem"] == 3 and iki["atlanan"] == 1           # 3. eşzamanlı işlem atlandı
    # tavansız: aynı özkaynakla 3 işlem açılır (+1 -1 +2 = +2R ≈ %2), sonra +1R
    assert tam["toplam_getiri"] == pytest.approx(1.02 * 1.01 - 1, rel=1e-9)


@pytest.mark.parametrize("n,ort,durum", [(10, 0.5, "erken"), (60, -0.1, "izle"), (120, -0.01, "dur"),
                                         (120, 0.05, "izle"), (220, 0.1, "uygun"), (220, -0.02, "dur")])
def test_ileri_test_kurallari(n, ort, durum):
    bek = {"ort_r": 0.1, "sd": 1.5}
    assert ileri_test.karar(n, ort, n * ort, bek)["durum"] == durum


def test_ileri_test_uyari_bandi():
    bek = {"ort_r": 0.1, "sd": 1.5}
    k = ileri_test.karar(60, -0.4, -24.0, bek)   # alt bant: 6 - 2*1.5*sqrt(60) ≈ -17.2
    assert k["uyari"] and "bandının altında" in k["metin"]


def test_ileri_test_motoru_baslangictan_once_islem_acmaz():
    d = {s: (veri.rastgele_yuruyus(5000, tohum=i, baslangic="2026-04-01"), pd.Series(dtype=float))
         for i, s in enumerate(["BTCUSDT", "ETHUSDT"])}
    son = min(df.index[-1] for df, _ in d.values())
    p = StratejiParam(tetik_tf="4h", rejim_tf="4h", btc_filtre=True)
    rp = ileri_test.hesapla(d, {}, son, p=p)
    for x in rp["islemler"] + rp["acik"]:
        assert pd.Timestamp(x["giris_zaman"]) >= ileri_test.BASLANGIC
    assert rp["ozet"]["islem"] == len(rp["islemler"])
    assert all(x["neden"] != "donem_sonu" for x in rp["islemler"])


def test_backtest_verisi_bitis_ayinda_kesilir(tmp_path):
    idx = pd.date_range("2026-10-30", "2026-11-03", freq="1h", tz="UTC", inclusive="left")
    df = pd.DataFrame({c: 1.0 for c in veri.SUTUNLAR}, index=idx)
    df.index.name = "zaman"
    df.to_csv(tmp_path / "XUSDT_1h.csv")
    (tmp_path / "XUSDT_1h.bos").write_text("\n".join(f"{y}-{m:02d}" for y in range(2020, 2027) for m in range(1, 13)
                                                     if (y, m) != (2026, 10) and (y, m) != (2026, 11)))
    (tmp_path / "XUSDT_fonlama.bos").write_text("\n".join(f"{y}-{m:02d}" for y in range(2020, 2027) for m in range(1, 13)))
    m, _ = veri.gecmis_yukle("XUSDT", "2026-10", "2026-10", onbellek=tmp_path)
    assert m.index[-1] < pd.Timestamp("2026-11-01", tz="UTC")
    assert len(m) == 48
