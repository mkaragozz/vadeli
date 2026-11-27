_Dönem 2022-01-01 → 2026-10-31, holdout 2025-01-01 → 2026-10. Maliyetler dahil. Taban: `4h tetik 20/10, ATR14x3.0, EMA200(4h), BTC rejim, OI↑(6)` (p8abf0564)._

### Kenar varyantları

| Varyant | İşlem | Ort. R | t | PF(R) | Holdout R (t) | Daha iyi yıl | Eşikler (ort. R) | Kabul |
|---|---|---|---|---|---|---|---|---|
| taban | 2708 | 0.115 | 2.6 | 1.30 | 0.087 (1.9) | - | - | - |
| +rs | 2116 | 0.107 | 2.2 | 1.28 | 0.049 (1.0) | 2/5 | 0.093 / 0.107 / 0.091 | ✗ ~~a~~ ~~b~~ ~~c~~ ~~d~~ e |
| +basabas | 2714 | 0.112 | 2.5 | 1.29 | 0.087 (1.9) | 1/5 | 0.112 / 0.115 / 0.115 | ✗ ~~a~~ ~~b~~ ~~c~~ ~~d~~ e |
| 1g_tetik | 451 | 0.205 | 1.3 | 1.45 | 0.151 (0.5) | 2/5 | 0.119 / 0.205 / 0.181 | ✗ a ~~b~~ c d ~~e~~ |

Yıllık ort. R: taban: -0.055/0.196/0.208/0.051/0.129 · +rs: -0.019/0.155/0.279/0.020/0.087 · +basabas: -0.056/0.190/0.201/0.054/0.126 · 1g_tetik: -0.155/-0.005/0.652/0.313/-0.053

Kabul: a = ort. R en az +0.02 yüksek, b = ≥4/5 yıl daha iyi, c = holdout daha iyi, d = ≥2/3 eşik daha iyi, e = işlem ≥ tabanın %40'ı; üstü çizili = sağlanmadı.

### K2 — Tek hesap portföy (22 sembol, ortak özkaynak, %1 risk/işlem)

| Açık risk tavanı | İşlem | Atlanan | Toplam | Yıllık | Max DD | Yıllık/DD | Sharpe |
|---|---|---|---|---|---|---|---|
| yok | 2708 | 0 | 265.0% | 30.9% | -55.0% | 0.56 | 0.68 |
| 8R | 840 | 1868 | 94.0% | 16.6% | -38.2% | 0.44 | 0.72 |
| 5R ← | 468 | 2240 | 50.9% | 21.3% | -26.4% | 0.81 | 0.79 |
| 3R | 282 | 2426 | 13.8% | 7.3% | -18.8% | 0.39 | 0.42 |

Tavanlı satırlar: aynı saatte açılan sinyallerin sırası 20 kez rastgele karıştırıldı, medyan gösteriliyor.

| İşlem başı risk | Tavan | Yıllık (medyan) | Yıllık aralığı | Max DD | Yıllık/DD |
|---|---|---|---|---|---|
| %0.25 | yok | 14.3% | 14.3% … 14.3% | -16.6% | 0.86 |
| %0.25 | 5R | 6.0% | 4.4% … 7.5% | -7.1% | 0.85 |
| %0.5 | yok | 24.0% | 24.0% … 24.0% | -30.5% | 0.79 |
| %0.5 | 5R | 11.5% | 8.4% … 14.7% | -13.7% | 0.84 |
| %1.0 | yok | 30.9% | 30.9% … 30.9% | -55.0% | 0.56 |
| %1.0 | 5R | 21.3% | 14.5% … 27.8% | -26.4% | 0.81 |

Aynı anda açık pozisyon (tavansız): en çok 22, ortalama 9.3. Karşılaştırma — eski model (22 ayrı alt hesap, eşit ağırlık): yıllık 2.7%, max DD -4.0%.

### K1 — Hayatta kalma yanlılığı (2022-01'in hacimce ilk 60'ı)

* Tüm evren (60 sembol): 6574 işlem, ort. R 0.062 (t 2.8), holdout 0.048 (t 1.6), kârlı sembol 60.0%
* Yıllık ort. R: -0.010 / 0.093 / 0.102 / -0.007 / 0.115
* Ana set dışında kalanlar: ort. R 0.025 (3866 işlem), holdout 0.016
* Listeden çıkanlar: ort. R 0.109 (282 işlem) — LUNA 0.98 (9), MATIC -0.01 (67), EOS 0.11 (77), SXP 0.13 (89), ANT 0.06 (40)
