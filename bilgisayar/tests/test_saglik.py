"""Sağlık kontrolleri: kenarı olmayan veride sistem kâr etmemeli; sinyal kaydırma mantıklı etki etmeli."""
from __future__ import annotations

import numpy as np

from vadeli import veri
from vadeli.backtest import calistir
from vadeli.strateji import MaliyetParam, RiskParam, StratejiParam

P = StratejiParam()


def test_rastgele_yuruyuste_kar_yok():
    """20 farklı rastgele yürüyüşte medyan sonuç maliyetlerden sonra negatif olmalı,
    ve kârlı tohum oranı yarıdan az olmalı."""
    getiriler = []
    for tohum in range(20):
        df = veri.rastgele_yuruyus(15_000, tohum=tohum)
        getiriler.append(calistir(df, P, RiskParam(), MaliyetParam()).metrik["toplam_getiri"])
    g = np.array(getiriler)
    assert np.median(g) < 0, g
    assert (g > 0).mean() < 0.5, g


def test_maliyetsiz_rastgele_yuruyuste_beklenti_sifir_civari():
    rs = []
    for tohum in range(20):
        df = veri.rastgele_yuruyus(15_000, tohum=100 + tohum)
        s = calistir(df, P, RiskParam(), MaliyetParam(komisyon=0, kayma=0, fonlama_mod="yok"))
        rs.append(s.metrik["ort_r"])
    # işlem başına ortalama R sıfırdan anlamlı sapmamalı
    assert abs(np.mean(rs)) < 0.08, rs


def test_gelecek_bilgisi_kaydirma_asiri_iyi_gorunur():
    """-1 kaydırma (sinyali bir mum ERKEN bilmek) rastgele veride bile belirgin kâr üretir.
    Bu, motorun gelecek bilgisine duyarlı olduğunu (ve normal çalıştırmanın bunu kullanmadığını) gösterir."""
    normal, erken = [], []
    for tohum in range(8):
        df = veri.rastgele_yuruyus(10_000, tohum=200 + tohum)
        normal.append(calistir(df, P, RiskParam(), MaliyetParam()).metrik["ort_r"])
        erken.append(calistir(df, P, RiskParam(), MaliyetParam(), kaydir=-1).metrik["ort_r"])
    assert np.mean(erken) > np.mean(normal) + 0.3
