"""Look-ahead sızıntısı ve işlem mekaniği testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vadeli import veri
from vadeli.backtest import PozisyonTakip, calistir, fonlama_dizisi, pozisyon_ac, tek_sinyal_simule
from vadeli.strateji import MaliyetParam, RiskParam, StratejiParam, hazirla, likidasyon_fiyati, rejim_hizala, risk_hesapla

P = StratejiParam()
M0 = MaliyetParam(komisyon=0, kayma=0, fonlama_mod="yok")


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return veri.rastgele_yuruyus(6000, tohum=3, surukleme=0.0005)


def test_gelecek_degistirilince_gecmis_ayni(df):
    """Satır i'den sonraki veriyi bozmak, i ve öncesindeki HİÇBİR değeri değiştirmemeli."""
    h1 = hazirla(df, P)
    for kes in (2000, 3001, 4502):
        bozuk = df.copy()
        bozuk.iloc[kes + 1:, :4] *= 1.7  # gelecek tamamen farklı
        bozuk.iloc[kes + 1:, 1] *= 1.1
        h2 = hazirla(bozuk, P)
        a = h1.iloc[: kes + 1]
        b = h2.iloc[: kes + 1]
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-12)


def test_kesik_veri_ile_tam_veri_ayni(df):
    """Canlıda veri son mumda biter: kesik veriyle hesaplanan son satır, tam verideki aynı satırla eşit olmalı."""
    h_tam = hazirla(df, P)
    for kes in (1500, 2222, 3333, 4444, 5999):
        h_kes = hazirla(df.iloc[: kes + 1], P)
        pd.testing.assert_series_equal(h_kes.iloc[-1], h_tam.iloc[kes], check_names=False, rtol=1e-9)


def test_4s_hizalama_tamamlanmis_mum():
    """4s mum (00-04) yalnızca 03:00 açılışlı 1s mumun kapanışından (04:00) itibaren görünmeli."""
    idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    c = np.arange(48, dtype=float) + 100
    df = pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1.0, "quote_volume": 1.0}, index=idx)
    r = rejim_hizala(df, "1h", "4h", ema_n=1)
    # 00:00-03:00 açılışlı mumlar: önceki 4s mum yok -> NaN, ama 03:00 mumu kapanınca (04:00) 00-04 dilimi tamam
    assert r["kapanis_r"].iloc[:3].isna().all()
    assert r["kapanis_r"].iloc[3] == c[3]          # 00-04 diliminin kapanışı = 03:00 mumunun kapanışı
    assert r["kapanis_r"].iloc[4] == c[3]          # 04:00 mumu hâlâ 00-04 dilimini görür
    assert r["kapanis_r"].iloc[6] == c[3]
    assert r["kapanis_r"].iloc[7] == c[7]          # 04-08 dilimi 07:00 mumunun kapanışında tamamlanır


def test_eksik_son_4s_dilimi_kullanilmaz():
    idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")  # 08:00-10:00 dilimi eksik
    c = np.arange(10, dtype=float) + 1
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0, "quote_volume": 1.0}, index=idx)
    b = veri.yeniden_ornekle(df, "4h")
    assert len(b) == 2 and b.index[-1] == pd.Timestamp("2024-01-01 04:00", tz="UTC")


def test_kanal_shift_mevcut_mumu_icermez(df):
    h = hazirla(df, P)
    i = 500
    beklenen = df["high"].iloc[i - P.giris_n:i].max()
    assert h["kanal_ust"].iloc[i] == pytest.approx(beklenen)
    assert h["kanal_alt"].iloc[i] == pytest.approx(df["low"].iloc[i - P.giris_n:i].min())
    # Sinyal satırında kapanış kanalın üstünde, ama kanal bu mumun high'ını içermiyor
    sinyal = h.index[h["long_sinyal"]]
    assert len(sinyal) > 0
    for t in sinyal[:20]:
        satir = h.loc[t]
        assert satir["close"] > satir["kanal_ust"]
        assert satir["rejim"] == 1


def test_giris_sonraki_acilista(df):
    s = calistir(df, P, RiskParam(), M0)
    h = hazirla(df, P)
    assert len(s.islemler) > 5
    for _, t in s.islemler.head(30).iterrows():
        i = h.index.get_loc(t["giris_zaman"])
        onceki = h.iloc[i - 1]
        # giriş fiyatı = giriş mumunun açılışı (kayma 0)
        assert t["giris"] == pytest.approx(h["open"].iloc[i])
        # sinyal bir önceki mumda
        assert onceki["long_sinyal" if t["yon"] == "LONG" else "short_sinyal"]


def test_kayma_aleyhe(df):
    m = MaliyetParam(komisyon=0, kayma=0.001, fonlama_mod="yok")
    s = calistir(df, P, RiskParam(), m)
    h = hazirla(df, P)
    t = s.islemler.iloc[0]
    acilis = h.loc[t["giris_zaman"], "open"]
    if t["yon"] == "LONG":
        assert t["giris"] == pytest.approx(acilis * 1.001)
    else:
        assert t["giris"] == pytest.approx(acilis * 0.999)


def _poz(yon=1, giris=100.0, stop=95.0, liq=80.0):
    return PozisyonTakip(yon=yon, giris=giris, adet=1.0, stop=stop, likidasyon=liq, teminat=20.0, risk_usdt=5.0,
                         kaldirac=5, giris_zaman=pd.Timestamp("2024-01-01", tz="UTC"), atr_kat=3.0, maliyet=M0)


def test_stop_mum_icinde_stop_fiyatindan():
    p = _poz()
    assert p.acilis_isle(99.0) is None
    x = p.mum_ici_isle(h=101, l=94)
    assert x == (95.0, "stop")


def test_stop_bosluk_acilistan_dolar():
    p = _poz()
    assert p.acilis_isle(93.0) == (93.0, "stop")  # stopun altında açılış: stop fiyatından değil, açılıştan


def test_likidasyon_sadece_bosluk_ile():
    p = _poz()
    assert p.acilis_isle(79.0) == (80.0, "likidasyon")
    s = p.kapat(80.0, "likidasyon")
    assert s["brut"] == -20.0  # teminatın tamamı


def test_short_stop():
    p = _poz(yon=-1, giris=100, stop=105, liq=120)
    assert p.mum_ici_isle(h=106, l=99) == (105, "stop")


def test_takip_stopu_sadece_lehine():
    p = _poz()
    p.kapanis_isle(c=110, atr=2, cikis_sinyali=False, fonlama_orani=0)
    assert p.stop == pytest.approx(104)
    p.kapanis_isle(c=100, atr=2, cikis_sinyali=False, fonlama_orani=0)
    assert p.stop == pytest.approx(104)  # geri gitmez


def test_kanal_cikisi_sonraki_acilista():
    p = _poz()
    p.kapanis_isle(c=101, atr=1, cikis_sinyali=True, fonlama_orani=0)
    assert p.bekleyen_cikis
    assert p.acilis_isle(102.0) == (102.0, "kanal")


def test_kaldirac_kurali():
    r = RiskParam(hesap=1000, risk_yuzde=1, max_kaldirac=5, mmr=0.005, liq_oran=0.5)
    m = MaliyetParam()
    for giris, stop in ((100, 97), (100, 90), (100, 99.5), (100, 70)):
        x = risk_hesapla(giris, stop, 1, r, m)
        assert x["kaldirac"] <= 5 and x["kaldirac"] >= 1
        if x["kaldirac"] > 1:  # 1x'te kural uygulanamaz (kaldıraçsız)
            assert x["stop_liq_orani"] <= 0.5 + 1e-9
        assert x["risk_usdt"] <= 10.0 + 1e-6
        assert x["teminat"] <= 1000
    # kaldıraç riski değiştirmez: tavan 2x veya 5x, aynı risk
    a = risk_hesapla(100, 98, 1, RiskParam(max_kaldirac=2), m)
    b = risk_hesapla(100, 98, 1, RiskParam(max_kaldirac=5), m)
    assert a["risk_usdt"] == pytest.approx(b["risk_usdt"])
    assert a["teminat"] > b["teminat"]


def test_likidasyon_fiyati_yonu():
    assert likidasyon_fiyati(100, 1, 5, 0.005) == pytest.approx(80.5)
    assert likidasyon_fiyati(100, -1, 5, 0.005) == pytest.approx(119.5)


def test_stop_her_zaman_likidasyondan_once(df):
    """Açılış boşluğu olmadan likidasyon olmamalı: stop daima daha yakın."""
    s = calistir(df, P, RiskParam(max_kaldirac=20), MaliyetParam())
    assert (s.islemler["neden"] == "likidasyon").sum() == 0


def test_fonlama_kapanis_aninda():
    idx = pd.date_range("2024-01-01 05:00", periods=6, freq="1h", tz="UTC")
    f = pd.Series([0.0003], index=[pd.Timestamp("2024-01-01 08:00", tz="UTC")])
    d = fonlama_dizisi(idx, f, MaliyetParam())
    # 07:00 açılışlı mum 08:00'de kapanır
    assert list(d) == [0, 0, 0.0003, 0, 0, 0]
    s = fonlama_dizisi(idx, None, MaliyetParam(fonlama_mod="sabit"))
    assert s[2] == 0.0001 and s.sum() == 0.0001


def test_fonlama_isareti():
    p = _poz()
    p.kapanis_isle(c=100, atr=1, cikis_sinyali=False, fonlama_orani=0.001)
    assert p.fonlama == pytest.approx(0.1)  # long pozitif oranda öder
    q = _poz(yon=-1, stop=105, liq=120)
    q.kapanis_isle(c=100, atr=1, cikis_sinyali=False, fonlama_orani=0.001)
    assert q.fonlama == pytest.approx(-0.1)  # short alır


def test_tek_sinyal_simulasyonu_backtest_ile_ayni(df):
    """Geçmiş sinyal sonuç hesabı, backtestteki aynı işlemle birebir aynı çıkışı vermeli."""
    s = calistir(df, P, RiskParam(), M0)
    h = hazirla(df, P)
    for _, t in s.islemler.head(15).iterrows():
        if t["neden"] == "donem_sonu":
            continue
        sinyal_zamani = h.index[h.index.get_loc(t["giris_zaman"]) - 1]
        x = tek_sinyal_simule(h, sinyal_zamani, 1 if t["yon"] == "LONG" else -1, P, RiskParam(), M0)
        assert x["durum"] == "kapali"
        assert x["neden"] == t["neden"]
        assert x["cikis_fiyat"] == pytest.approx(t["cikis_fiyat"])
        assert x["cikis_zaman"] == t["cikis_zaman"].isoformat()


def test_kapanmamis_mum_atilir():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame({k: [1.0, 2, 3] for k in veri.SUTUNLAR}, index=idx)
    simdi = int(pd.Timestamp("2024-01-01 02:30", tz="UTC").timestamp() * 1000)
    assert len(veri.kapanmamislari_at(df, "1h", simdi)) == 2


def test_4s_tetik_kesik_veri_ile_tam_veri_ayni(df):
    """4s tetik modunda canlı (1s depodan yeniden örnekleme, eksik son dilim atılır) ile backtest aynı satırı üretir."""
    from dataclasses import replace

    p4 = replace(P, tetik_tf="4h", rejim_tf="4h")
    tam = hazirla(veri.yeniden_ornekle(df, "4h"), p4)
    for kes in (3001, 4002, 5003, 5999):  # 4s dilimin ortasında kesilen veri
        h = hazirla(veri.yeniden_ornekle(df.iloc[: kes + 1], "4h"), p4)
        son = h.index[-1]
        assert son + pd.Timedelta(hours=4) <= df.index[kes] + pd.Timedelta(hours=1)  # eksik dilim yok
        pd.testing.assert_series_equal(h.iloc[-1], tam.loc[son], check_names=False, rtol=1e-9)
