# RAPOR — Binance USDT-M vadeli sinyal stratejisi: gerçek veri doğrulaması

_Veri: 2020-01 → 2026-10, Binance USDT-M 1s mumlar + gerçek fonlama. Tüm sayılar maliyet dahildir.
Ayrıntılı tablolar: `raporlar/ozet.md` (otomatik), `raporlar/*.csv`, panoda **Backtest** ekranı. Deneme günlüğü: `DENEYLER.md`._

> Hiçbir sonuç kâr garantisi değildir. Geçmiş performans geleceği göstermez. Yatırım tavsiyesi değildir.

## 1. Sonuç (kısa)

| | Şartname stratejisi (1s tetik + 4s EMA200) | 4s tetik + BTC rejimi (seçilen) |
|---|---|---|
| İşlem başına ort. R (22 sembol, 2020–2026) | **−0.005** (t = −0.7) | **+0.095** (t = 4.0) |
| Profit factor (R) | 0.99 | 1.26 |
| Eşit ağırlıklı portföy (yıllık / max düşüş) | −1.0% / −21.4% | +3.7% / −4.9% |
| Kârlı yıl | 3/7 | 7/7 |
| Kârlı sembol (22 / güncel 50) | 45% / 50% | 91% / 64% (≥1.5 yıl geçmişliler: 88%) |
| Izgarada kârlı kombinasyon | 35% | 100% |
| Walk-forward test (2022–26) | −0.014 R, 2/5 yıl + | +0.079 R, 4/5 yıl + |
| **Holdout 2025-01 → 2026-10** | −0.002 R (t −0.2) | **+0.020 R (t 0.7)** |
| Ön kayıtlı canlı kriterleri | **geçmedi** | geçti |

**Bu strateji gerçek veride şunu gösterdi:**

1. **Şartnamedeki strateji (1s tetik) kenarsızdır.** Maliyetsiz hâlde +0.054 R olan işlem başı beklenti, taker
   komisyonu + kayma + fonlama ile −0.005 R'ye düşüyor. 7 yılın 4'ünde zarar, sembollerin yarısından fazlasında zarar,
   54 parametre kombinasyonunun %65'i zararda, walk-forward negatif. **Canlıya uygun değil.**
2. **4 saatlik tetik + BTC rejim filtresi** ön kayıtlı yedi kriterin hepsini geçti: her yıl pozitif, parametrelere
   duyarsız (54 kombinasyonun hepsi pozitif), walk-forward pozitif, sembollerin çoğunda tutarlı, karıştırılmış/rastgele
   veride zarar ediyor (yani kenar trend yapısından geliyor, hatadan değil).
3. **Ancak kenar son iki yılda neredeyse kayboldu.** 2020–2024 arası işlem başına +0.07…+0.18 R iken 2025'te +0.017,
   2026'da +0.023 R; holdout t-istatistiği 0.7, yani **sıfırdan istatistiksel olarak ayırt edilemiyor.** Getiri de
   mütevazı: %1 riskle yılda ~%3.7, al-tut'un çok altında (BTC al-tut ≈ +980%).
4. Seçilim yanlılığı: 8 varyant denendi, en iyisi seçildi. 4s_tetik (BTC filtresiz) de neredeyse aynı sonucu
   verdiği için bulgunun özü "4s tetik 1s'ten iyi"dir; BTC filtresinin katkısı küçüktür.

**Öneri: gerçek parayla anlamlı büyüklükte canlıya UYGUN DEĞİL.** Kullanılacaksa:
* Önce en az 2–3 ay yalnızca izleyin (panodaki **Geçmiş** ekranı canlı sonuçları backtest beklentisiyle yan yana gösterir).
* Sonra çok küçük risk (%0.25–0.5/işlem) ve düşük kaldıraç tavanı. Kaldıraç kârı değil, yalnızca teminatı değiştirir.
* Stop'u **mutlaka borsada** girin; sistem emir göndermez.
* Canlı ort. R 100+ işlemden sonra hâlâ ≤ 0 ise durun.

## 1b. Ek: Türev ve piyasa verileri (CoinGlass / CoinGecko / CoinMarketCap / TradingView isteği)

**Kaynak kararları**
* **TradingView kullanılmadı:** resmi veri API'si yok; sayfa kazımak kullanım şartlarına aykırı ve kırılgan.
  "Kripto ısı haritası" siteleri CoinGecko/CMC verisinin görselleştirmesidir; panoda **Piyasa** ekranı aynı ısı
  haritasını CoinGecko verisiyle kendisi çiziyor.
* **CoinGlass'ın Binance verisi** (açık pozisyon, büyük trader ve tüm hesaplar long/short oranı, taker alım/satım) doğrudan
  Binance'in herkese açık uç noktalarından alındı. 2021-12'den beri 5 dakikalık geçmişi resmi arşivde var, bu yüzden
  **backtest edilebildi**. CoinGlass'ın kendi API'si (çoklu borsa) anahtar istediği için isteğe bağlı (`COINGLASS_API_KEY`).
* **CoinGecko** (anahtarsız): toplam piyasa değeri, BTC/ETH dominansı, stabilcoin payı, ilk 100 coin ısı haritası.
  **CoinMarketCap** isteğe bağlı (`CMC_API_KEY`). Bunların ücretsiz geçmişi olmadığı/kısa olduğu için **sinyale girmez**,
  yalnız bağlam olarak gösterilir (backtest edilemeyen veri sinyale konmaz).

**Sonuç (2022-01 → 2026-10, 22 sembol, maliyetler dahil, ön kayıtlı kurallar — `DENEYLER.md` §1, D10):**

| | İşlem | Ort. R | Holdout 2025-26 ort. R (t) | Kârlı sembol |
|---|---|---|---|---|
| 4s tetik + BTC rejimi (önceki varsayılan) | 4357 | 0.083 | 0.020 (0.7) | 77% |
| **+ açık pozisyon teyidi (yeni varsayılan)** | 2708 | **0.115** | **0.087 (1.9)** | 73% |
| + fonlama vetosu | 4288 | 0.088 | 0.020 | 82% |
| + long/short kalabalık filtresi | 4276 | 0.086 | 0.023 | 77% |
| + taker teyidi | 3188 | 0.071 | 0.035 | 59% |
| 1s şartname stratejisi + en iyi türev filtresi | 8822 | −0.011 | 0.023 | 32% |

* **Kırılımda açık pozisyonun artıyor olması** (yeni para girişi) işe yarayan tek filtre oldu: işlemlerin ~%38'ini eliyor,
  kalanların ortalaması ve son iki yıldaki sonucu belirgin biçimde daha iyi. Eşik seçimine duyarsız (3/3 ayarda daha iyi).
* Fonlama ve taker filtreleri işe yaramadı; long/short kalabalığının etkisi gürültü düzeyinde.
* 1 saatlik şartname stratejisini hiçbir türev verisi kâra çevirmedi.
* **Güncel değerlendirme:** önceki "kenar son iki yılda kayboldu" bulgusu, açık pozisyon teyidi ile zayıfladı (holdout
  +0.087 R, t 1.9). Ancak bu bir kez daha seçilmiş bir sonuç (5 filtre denendi) ve t < 2. Öneri değişmedi:
  **önce izleme, sonra çok küçük risk.** Kanıt güçlendi ama "güvenilir kâr" seviyesinde değil.

## 1c. Geliştirme turu 2 ve ileri test (2026-11-26)

Ayrıntı: `DENEYLER.md` §2–§3 ve D12–D15 (kurallar sonuçlardan önce yazılıp kaydedildi), tablolar `raporlar/ozet_tur2.md`.

**1. Yeni kenar varyantlarının hiçbiri kabul edilmedi; strateji değişmedi.** Göreli güç filtresi, başabaş stop ve günlük
tetik denendi. Günlük tetik en yüksek ortalamayı gösterdi (+0.205 R), ama bu tek bir yıldan (2024) geliyor. 5 yılın 3'ünde
negatif, işlem sayısı da çok az. Önceden yazılan kural onu eledi.

**2. Tek hesap gerçeği: risk eski raporun gösterdiğinden çok büyük.** Eski portföy rakamları 22 ayrı alt hesabın
ortalamasıydı. Gerçekte tek hesapta aynı anda ortalama **9** (en çok 22) pozisyon açık oluyor; çoğu aynı yönde.

| İşlem başı risk | Açık pozisyon tavanı | Yıllık (medyan) | Max düşüş |
|---|---|---|---|
| %1 | yok | %31 | **−%55** |
| %1 | 5 | %21 | −%26 |
| %0.5 | 5 | %11.5 | −%14 |
| %0.25 | 5 | %6 | −%7 |

Önceden yazılan kural **en fazla 5 açık pozisyonu** seçti. Panoda "Açık pozisyon / tavan" göstergesi var; tavan doluyken
yeni sinyale girmeyin. Tavanla sinyallerin çoğu atlanır ve hangilerinin alındığı şansa bağlıdır. Bu yüzden yıllık sonuç
geniş bir aralıkta oynar (%1 riskte %15–%28).

**3. Hayatta kalma yanlılığı: ana set sonuçları yaklaşık iki kat iyimser.** Ana set bugün hâlâ büyük olan coinlerden
seçilmişti. 2022 başında bilinebilecek ilk 60 coinde işlem başına sonuç **+0.062 R** (ana sette +0.115). Ana set dışındaki
coinlerde sonuç **+0.025 R**, yani maliyetlerden sonra neredeyse sıfır. Panoda bu coinlerin sinyalleri **"ana set dışı"**
olarak işaretleniyor ve "Yalnız ana set" filtresi eklendi.

**4. İleri test başladı.** Dondurulmuş strateji, hiçbir analizde kullanılmamış veride (2026-11-01'den beri, 22 sembol)
Binance arşivinden her gün yeniden hesaplanıyor. Bilgisayarın açık kalması gerekmiyor. Karar kuralları önceden yazıldı:
100. işlemde ortalama ≤ 0 ise DUR; 200. işlemde pozitif ve beklenti bandı içindeyse küçük riskle canlı uygun.
İlk sonuç: 16 işlem, +0.365 R. Bu erken bir sonuç ve henüz anlamlı değil.

**Güncellenmiş öneri:** ileri test 100 işleme ulaşana kadar (yaklaşık 2–3 ay) gerçek para yok. Sonra en fazla **%0.25–0.5
risk/işlem**, **en çok 5 açık pozisyon** ve yalnız ana set. Gerçekçi beklenti, iyimser backtest'in yarısı kadardır.

## 2. Yöntem

**Veri.** Binance USDT-M perpetual sözleşmelerinin 1 saatlik mumları ve gerçekleşmiş fonlama oranları, Binance'in resmi
herkese açık veri arşivinden (`data.binance.vision`, aylık ZIP) 2020-01 → 2026-10 arası indirildi ve `veri_onbellek/`
altına CSV olarak kaydedildi. (Bu çalışmanın yapıldığı sunucu ABD'de olduğu için `fapi.binance.com` REST API'si
HTTP 451 ile yanıt verdi; arşiv aynı borsanın aynı verisidir. Canlı tarayıcı REST/WebSocket kullanır.)

* **Ana set (22 sembol):** zorunlu BTC, ETH, SOL, BNB, XRP + hacimce büyük ve 2021 öncesinden beri işlem gören
  DOGE, ADA, LINK, LTC, AVAX, DOT, TRX, BCH, ETC, ATOM, FIL, AAVE, XLM, NEAR, UNI, ZEC, SAND.
* **Güncel ilk 50:** 2026-10 ayının USDT hacmine göre ilk 50 sözleşme (arşivden hesaplandı). Bu listenin yaklaşık
  yarısı 2025-2026'da açılmış hisse/emtia/ETF perpetual'ları (XAU, CL, MU, NVDA, TSLA, SOXL…) ve yeni coinlerdir;
  geçmişleri kısadır. Her sembol kendi mevcut geçmişiyle test edildi.

**Hesap modeli.** Her sembol 1000 USDT'lik ayrı alt hesap, işlem başına %1 risk (stop + iki yön maliyet dahil),
kaldıraç tavanı 5x ve stop ≤ likidasyon mesafesinin %50'si kuralı, bileşik büyüme. Portföy = sembollerin günlük
getirilerinin eşit ağırlıklı ortalaması. Maliyetler: taker %0.05/yön, kayma %0.03/yön (stop dolumlarında da),
**gerçek fonlama** (işaretli: long pozitif oranda öder, short alır). İşlem başına **R** = net kâr ÷ başlangıç riski.

**Zamanlama (look-ahead yok).** Sinyal i. mumun kapanışında, giriş (i+1). mumun açılışında. 4s rejim yalnızca
tamamlanmış 4s mumdan. Kanal `shift(1)`. Stop mum içinde stop fiyatından, açılış boşluğunda açılış fiyatından dolar.
Testler (`tests/`) bunları ve "gelecek veri değişince geçmiş değişmez", "kesik veri = tam veri" özelliklerini kanıtlar.

**Aşırı uyum disiplini.** Karar kuralları ve alternatif listesi sonuçlar görülmeden `DENEYLER.md §0`'da sabitlendi.
Izgara/walk-forward seçimleri yalnız eğitim dilimine bakar. 2025-01 → 2026-10 dönemi "holdout" olarak ayrıca raporlanır.
Hiçbir parametre test sonucuna bakılarak değiştirilmedi.

## 3. Sonuç tabloları

Aşağıdaki tablolar `python tarayici.py backtest` çıktısından (`raporlar/ozet.md`) alınmıştır.

_Oluşturma: 2026-11-25T22:57 UTC — veri: Binance USDT-M resmi arşivi (data.binance.vision), 1s mum + gerçek fonlama_

### Varyant karşılaştırması (ana set, tüm dönem, eşit ağırlıklı portföy)

| Varyant | İşlem | Kazanma | Ort. R | t | PF(R) | Portföy toplam | Yıllık | Max DD | Sharpe | Kârlı sembol | Kârlı yıl | Holdout ort. R (t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| temel | 21721 | 33.7% | -0.005 | -0.7 | 0.99 | -6.9% | -1.0% | -21.4% | -0.07 | 45.5% | 3/7 | -0.002 (-0.2) |
| 4s_tetik | 7009 | 36.0% | 0.078 | 3.7 | 1.21 | 28.1% | 3.7% | -6.3% | 0.69 | 86.4% | 6/7 | 0.011 (0.4) |
| genis_cikis | 17137 | 33.9% | 0.001 | 0.1 | 1.00 | -0.7% | -0.1% | -17.0% | 0.03 | 45.5% | 5/7 | -0.003 (-0.2) |
| hacim_filtre | 18433 | 33.7% | 0.001 | 0.1 | 1.00 | -0.3% | -0.0% | -16.7% | 0.04 | 50.0% | 5/7 | 0.006 (0.4) |
| vol_filtre | 21257 | 33.7% | -0.006 | -0.8 | 0.98 | -7.3% | -1.1% | -22.2% | -0.08 | 40.9% | 2/7 | 0.002 (0.1) |
| btc_rejim | 17448 | 33.3% | -0.006 | -0.7 | 0.98 | -7.2% | -1.1% | -20.6% | -0.09 | 40.9% | 2/7 | -0.005 (-0.3) |
| sadece_long | 10333 | 33.1% | 0.004 | 0.3 | 1.01 | 2.3% | 0.3% | -15.0% | 0.09 | 54.5% | 4/7 | 0.034 (1.2) |
| 4s_tetik_btc | 5781 | 35.9% | 0.095 | 4.0 | 1.26 | 28.3% | 3.7% | -4.9% | 0.70 | 90.9% | 7/7 | 0.020 (0.7) |

### Ön kayıtlı 'canlıya uygun' kriterleri (DENEYLER.md §0)

| Varyant | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Sonuç |
|---|---|---|---|---|---|---|---|---|
| temel | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | geçmedi |
| 4s_tetik | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | GEÇTİ |
| genis_cikis | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | – | geçmedi |
| hacim_filtre | ✗ | ✓ | ✗ | ✓ | ✗ | ✓ | – | geçmedi |
| vol_filtre | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | – | geçmedi |
| btc_rejim | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | – | geçmedi |
| sadece_long | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | – | geçmedi |
| 4s_tetik_btc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | GEÇTİ |

1: ort. R>0 ve PF≥1.10 · 2: ≥5/7 yıl pozitif · 3: ≥%60 sembol kârlı · 4: ızgarada ≥%60 kombinasyon pozitif · 5: walk-forward test ortalaması >0 ve ≥3/5 yıl pozitif · 6: holdout (2025-01→2026-10) ort. R>0 · 7: karıştırılmış veride ort. R≤0.02 ve rastgele yürüyüşte medyan getiri<0 (– = bu varyant için çalıştırılmadı)

### Yıllık dilimler — temel  (`1h tetik 20/10, ATR14x3.0, EMA200(4h)`)

| Dilim | İşlem | Ort. R | t | Toplam R | Kazanma | Long R | Short R | Portföy getiri | Portföy DD | Kârlı sembol |
|---|---|---|---|---|---|---|---|---|---|---|
| 2020-01..2021-01 | 1944 | -0.006 | -0.2 | -11.5 | 30.6% | 15.3 | -26.8 | 0.0% | -9.9% | 42.9% |
| 2021-01..2022-01 | 3384 | 0.042 | 1.9 | 141.4 | 36.4% | 169.4 | -27.9 | 6.9% | -4.2% | 50.0% |
| 2022-01..2023-01 | 3257 | -0.009 | -0.5 | -29.2 | 36.3% | -82.8 | 53.7 | -2.0% | -8.8% | 36.4% |
| 2023-01..2024-01 | 3296 | -0.063 | -2.9 | -208.6 | 30.5% | -107.4 | -101.2 | -9.1% | -12.1% | 22.7% |
| 2024-01..2025-01 | 3418 | 0.001 | 0.1 | 4.2 | 34.1% | -37.6 | 41.8 | -0.3% | -6.1% | 54.5% |
| 2025-01..2026-01 | 3582 | 0.007 | 0.3 | 24.7 | 32.8% | 38.3 | -13.6 | 1.1% | -5.8% | 50.0% |
| 2026-01..2026-11 | 2840 | -0.014 | -0.6 | -40.5 | 34.0% | 50.3 | -90.8 | -2.2% | -11.7% | 31.8% |

### Yıllık dilimler — 4s_tetik_btc  (`4h tetik 20/10, ATR14x3.0, EMA200(4h), BTC rejim`)

| Dilim | İşlem | Ort. R | t | Toplam R | Kazanma | Long R | Short R | Portföy getiri | Portföy DD | Kârlı sembol |
|---|---|---|---|---|---|---|---|---|---|---|
| 2020-01..2021-01 | 512 | 0.139 | 2.0 | 71.1 | 34.0% | 62.7 | 8.4 | 4.7% | -3.0% | 61.9% |
| 2021-01..2022-01 | 915 | 0.129 | 2.7 | 117.9 | 37.5% | 115.7 | 2.2 | 6.0% | -2.1% | 63.6% |
| 2022-01..2023-01 | 915 | 0.073 | 2.1 | 66.4 | 40.3% | 0.3 | 66.1 | 3.3% | -3.6% | 81.8% |
| 2023-01..2024-01 | 815 | 0.179 | 2.7 | 146.0 | 35.7% | 95.5 | 50.5 | 6.3% | -4.6% | 72.7% |
| 2024-01..2025-01 | 880 | 0.130 | 1.2 | 114.6 | 32.4% | 138.1 | -23.4 | 4.7% | -3.9% | 59.1% |
| 2025-01..2026-01 | 960 | 0.017 | 0.5 | 16.1 | 37.7% | 33.2 | -17.1 | 1.2% | -3.8% | 54.5% |
| 2026-01..2026-11 | 784 | 0.023 | 0.5 | 18.3 | 31.9% | 58.8 | -40.5 | 0.6% | -4.9% | 63.6% |

### Sembol bazında — temel (1000 USDT, %1 risk, 5x tavan, gerçek fonlama)

| Sembol | Başlangıç | Toplam | Yıllık | Max DD | Sharpe | İşlem | Kazanma | PF | Ort. R | Long $ | Short $ | Likidasyon | Al-tut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FILUSDT | 2020-10-16 | 71.3% | 9.3% | -19.9% | 0.64 | 831 | 34.9% | 1.14 | 0.073 | 287 | 426 | 0 | -98.3% |
| ETHUSDT | 2020-01-01 | 50.8% | 6.2% | -31.2% | 0.46 | 987 | 35.2% | 1.11 | 0.050 | 739 | -230 | 0 | 1650.1% |
| SANDUSDT | 2021-01-25 | 40.8% | 6.1% | -29.1% | 0.46 | 851 | 34.5% | 1.10 | 0.048 | 148 | 260 | 0 | -51.5% |
| SOLUSDT | 2020-09-14 | 23.6% | 3.5% | -25.3% | 0.31 | 951 | 35.5% | 1.05 | 0.029 | 333 | -97 | 0 | 2734.9% |
| AVAXUSDT | 2020-09-23 | 22.5% | 3.4% | -21.9% | 0.31 | 937 | 36.8% | 1.06 | 0.028 | -20 | 244 | 0 | 109.4% |
| ADAUSDT | 2020-01-31 | 14.3% | 2.0% | -26.2% | 0.21 | 1008 | 34.8% | 1.03 | 0.021 | 327 | -185 | 0 | 253.2% |
| DOGEUSDT | 2020-07-10 | 11.6% | 1.8% | -31.5% | 0.19 | 917 | 34.7% | 1.03 | 0.019 | 163 | -46 | 0 | 1923.8% |
| ZECUSDT | 2020-02-05 | 6.9% | 1.0% | -48.1% | 0.14 | 1003 | 34.0% | 1.02 | 0.013 | 64 | 4 | 0 | 1813.6% |
| BTCUSDT | 2020-01-01 | 3.0% | 0.4% | -26.9% | 0.11 | 1019 | 32.8% | 1.01 | 0.012 | 243 | -213 | 0 | 981.0% |
| XLMUSDT | 2020-01-20 | 2.2% | 0.3% | -36.3% | 0.11 | 1046 | 32.6% | 1.01 | 0.011 | 186 | -164 | 0 | 169.4% |
| XRPUSDT | 2020-01-06 | -10.6% | -1.6% | -42.7% | -0.03 | 981 | 32.8% | 0.97 | -0.003 | 20 | -126 | 0 | 513.1% |
| NEARUSDT | 2020-10-15 | -11.7% | -2.0% | -27.4% | -0.08 | 936 | 35.3% | 0.97 | -0.007 | -190 | 73 | 0 | 296.7% |
| UNIUSDT | 2020-09-18 | -17.5% | -3.1% | -32.0% | -0.15 | 950 | 34.6% | 0.95 | -0.014 | -259 | 84 | 0 | 29.6% |
| LINKUSDT | 2020-01-17 | -23.6% | -3.9% | -47.5% | -0.20 | 1067 | 34.0% | 0.94 | -0.019 | 28 | -263 | 0 | 315.9% |
| AAVEUSDT | 2020-10-16 | -23.8% | -4.4% | -36.0% | -0.25 | 958 | 35.1% | 0.92 | -0.022 | -218 | -21 | 0 | 224.2% |
| BNBUSDT | 2020-02-10 | -28.7% | -4.9% | -41.3% | -0.22 | 1065 | 31.6% | 0.93 | -0.023 | 78 | -365 | 0 | 2710.7% |
| ETCUSDT | 2020-01-16 | -31.1% | -5.3% | -53.2% | -0.28 | 1018 | 30.5% | 0.93 | -0.028 | -182 | -129 | 0 | -6.7% |
| DOTUSDT | 2020-08-22 | -37.8% | -7.4% | -46.2% | -0.50 | 946 | 33.6% | 0.87 | -0.045 | -191 | -187 | 0 | -72.4% |
| ATOMUSDT | 2020-02-07 | -39.6% | -7.2% | -49.6% | -0.46 | 1048 | 34.8% | 0.87 | -0.043 | -260 | -137 | 0 | -67.5% |
| TRXUSDT | 2020-01-15 | -40.8% | -7.4% | -52.9% | -0.32 | 1121 | 31.4% | 0.90 | -0.039 | -46 | -361 | 0 | 1694.6% |
| LTCUSDT | 2020-01-09 | -50.8% | -9.9% | -59.5% | -0.65 | 1031 | 31.5% | 0.83 | -0.061 | -345 | -163 | 0 | 23.2% |
| BCHUSDT | 2020-01-01 | -60.7% | -12.8% | -66.9% | -0.81 | 1050 | 31.5% | 0.80 | -0.082 | -393 | -214 | 0 | 39.3% |

Çıkış nedenleri (temel): {'kanal': 10913, 'stop': 10803, 'donem_sonu': 5} — likidasyon: 0 — toplam komisyon+kayma etkisi ve fonlama: komisyon 6342 USDT, fonlama 1495 USDT (tüm alt hesaplar)

### Sembol bazında — 4s_tetik_btc (22 sembol)

| Sembol | Toplam | Yıllık | Max DD | Sharpe | İşlem | Kazanma | PF | Ort. R | Long $ | Short $ | Likidasyon | Al-tut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 98.5% | 10.6% | -7.5% | 1.07 | 314 | 37.6% | 1.57 | 0.235 | 964 | 20 | 0 | 973% |
| XLMUSDT | 82.4% | 9.3% | -19.6% | 0.61 | 267 | 36.7% | 1.67 | 0.327 | 945 | -121 | 0 | 172% |
| ETHUSDT | 72.3% | 8.3% | -9.0% | 0.89 | 291 | 35.7% | 1.50 | 0.202 | 660 | 64 | 0 | 1633% |
| SOLUSDT | 45.3% | 6.3% | -7.1% | 0.80 | 255 | 41.2% | 1.44 | 0.156 | 453 | 0 | 0 | 2735% |
| ADAUSDT | 42.8% | 5.4% | -15.0% | 0.66 | 268 | 38.4% | 1.36 | 0.144 | 261 | 167 | 0 | 256% |
| FILUSDT | 41.4% | 5.9% | -23.2% | 0.61 | 231 | 39.0% | 1.31 | 0.162 | 131 | 283 | 0 | -98% |
| AVAXUSDT | 38.6% | 5.5% | -10.9% | 0.60 | 256 | 37.5% | 1.31 | 0.140 | 335 | 51 | 0 | 109% |
| BCHUSDT | 34.2% | 4.4% | -17.7% | 0.47 | 272 | 34.9% | 1.30 | 0.128 | 380 | -38 | 0 | 39% |
| BNBUSDT | 31.3% | 4.1% | -10.1% | 0.51 | 274 | 35.8% | 1.27 | 0.109 | 362 | -49 | 0 | 2768% |
| DOGEUSDT | 27.9% | 4.0% | -13.8% | 0.47 | 243 | 35.8% | 1.25 | 0.111 | 258 | 20 | 0 | 1922% |
| NEARUSDT | 25.3% | 3.8% | -9.7% | 0.51 | 244 | 35.7% | 1.25 | 0.100 | 213 | 40 | 0 | 293% |
| XRPUSDT | 22.7% | 3.0% | -15.5% | 0.36 | 265 | 32.5% | 1.19 | 0.090 | 298 | -71 | 0 | 488% |
| ETCUSDT | 17.9% | 2.5% | -24.7% | 0.31 | 265 | 32.8% | 1.14 | 0.073 | 222 | -43 | 0 | -10% |
| DOTUSDT | 9.0% | 1.4% | -11.6% | 0.23 | 251 | 37.8% | 1.10 | 0.039 | 1 | 90 | 0 | -72% |
| LTCUSDT | 6.3% | 0.9% | -20.0% | 0.15 | 279 | 35.1% | 1.06 | 0.028 | 23 | 41 | 0 | 24% |
| AAVEUSDT | 3.9% | 0.6% | -11.7% | 0.12 | 242 | 37.2% | 1.05 | 0.021 | -35 | 74 | 0 | 224% |
| SANDUSDT | 3.7% | 0.6% | -9.0% | 0.12 | 222 | 35.1% | 1.05 | 0.022 | -64 | 101 | 0 | -51% |
| TRXUSDT | 3.7% | 0.5% | -17.4% | 0.10 | 271 | 35.1% | 1.03 | 0.022 | 237 | -200 | 0 | 1622% |
| LINKUSDT | 1.1% | 0.2% | -12.8% | 0.06 | 298 | 34.9% | 1.01 | 0.009 | 36 | -25 | 0 | 322% |
| UNIUSDT | 0.5% | 0.1% | -14.9% | 0.05 | 243 | 36.2% | 1.00 | 0.007 | -35 | 39 | 0 | 30% |
| ZECUSDT | -0.0% | -0.0% | -22.7% | 0.04 | 258 | 32.9% | 1.00 | 0.008 | 20 | -21 | 0 | 1722% |
| ATOMUSDT | -19.3% | -3.1% | -28.1% | -0.42 | 272 | 32.0% | 0.78 | -0.074 | -142 | -51 | 0 | -69% |

### Parametre sağlamlığı — temel

54 kombinasyon. Ort. R > 0 olan kombinasyon oranı: **35.2%**, portföyü kârlı kombinasyon oranı: **37.0%**. Medyan ort. R: -0.004, medyan portföy getirisi: -4.5%. En iyi/en kötü ort. R: 0.013 / -0.036.

### Walk-forward — temel (2 yıl eğitimde seç → sonraki yıl test)

| Test yılı | Eğitim | Seçilen | Eğitim ort. R | Test ort. R | Test işlem | Varsayılan param test R | Tüm komb. test medyan R | Seçilenin test yüzdeliği |
|---|---|---|---|---|---|---|---|---|
| 2022 | 2020-2021 | 40/20/4.0/200 | 0.051 | 0.028 | 1911 | -0.009 | 0.006 | 96.3% |
| 2023 | 2021-2022 | 55/20/4.0/200 | 0.033 | -0.071 | 1688 | -0.063 | -0.070 | 50.0% |
| 2024 | 2022-2023 | 40/5/4.0/200 | -0.013 | -0.013 | 2950 | 0.001 | 0.001 | 40.7% |
| 2025 | 2023-2024 | 40/10/4.0/200 | -0.018 | 0.039 | 2522 | 0.007 | 0.023 | 64.8% |
| 2026 | 2024-2025 | 55/20/2.0/200 | 0.059 | -0.052 | 2106 | -0.014 | -0.024 | 3.7% |

Walk-forward birleşik test ort. R (yıllık ortalamalar): -0.014; testte pozitif yıl: 2/5

### Parametre sağlamlığı — 4s_tetik_btc

54 kombinasyon. Ort. R > 0 olan kombinasyon oranı: **100.0%**, portföyü kârlı kombinasyon oranı: **100.0%**. Medyan ort. R: 0.047, medyan portföy getirisi: 14.9%. En iyi/en kötü ort. R: 0.145 / 0.005.

### Walk-forward — 4s_tetik_btc (2 yıl eğitimde seç → sonraki yıl test)

| Test yılı | Eğitim | Seçilen | Eğitim ort. R | Test ort. R | Test işlem | Varsayılan param test R | Tüm komb. test medyan R | Seçilenin test yüzdeliği |
|---|---|---|---|---|---|---|---|---|
| 2022 | 2020-2021 | 55/20/4.0/200 | 0.305 | 0.087 | 518 | 0.073 | 0.067 | 88.9% |
| 2023 | 2021-2022 | 55/20/4.0/200 | 0.234 | 0.157 | 497 | 0.179 | 0.074 | 81.5% |
| 2024 | 2022-2023 | 40/20/4.0/200 | 0.137 | 0.177 | 576 | 0.130 | 0.045 | 98.1% |
| 2025 | 2023-2024 | 40/20/4.0/200 | 0.187 | -0.049 | 651 | 0.017 | -0.020 | 20.4% |
| 2026 | 2024-2025 | 20/10/3.0/200 | 0.071 | 0.023 | 784 | 0.023 | 0.024 | 48.1% |

Walk-forward birleşik test ort. R (yıllık ortalamalar): 0.079; testte pozitif yıl: 4/5

### Sağlık kontrolleri — temel

| Test | İşlem | Ort. R | t | Toplam R | Not |
|---|---|---|---|---|---|
| Gerçek veri, getiriler karıştırılmış (tohum 0) | 22914 | -0.048 | -6.9 | -1097 | kârlı sembol 9.1% |
| Gerçek veri, getiriler karıştırılmış (tohum 1) | 22896 | -0.043 | -6.3 | -986 | kârlı sembol 9.1% |
| Gerçek veri, getiriler karıştırılmış (tohum 2) | 22949 | -0.055 | -8.2 | -1271 | kârlı sembol 4.5% |
| Rastgele yürüyüş (20 seri) | - | -0.049 | - | - | medyan getiri -24.3%, kârlı oran 10.0% |
| Sinyal 1 mum ERKEN (gelecek bilgisi!) | 21629 | 0.430 | 45.4 | 9299 | portföy 7726.9% |
| Normal | 21721 | -0.005 | -0.7 | -119 | portföy -6.9% |
| Sinyal 1 mum geç | 21652 | -0.011 | -1.4 | -239 | portföy -11.3% |
| Sinyal 2 mum geç | 21809 | -0.013 | -1.7 | -278 | portföy -13.2% |
| Maliyet: maliyetsiz | 21710 | 0.054 | 6.1 | 1171 | portföy 70.4% |
| Maliyet: yalniz_komisyon | 21710 | 0.020 | 2.4 | 440 | portföy 21.1% |
| Maliyet: tam | 21721 | -0.005 | -0.7 | -119 | portföy -6.9% |
| Maliyet: maker_benzeri | 21714 | 0.026 | 3.0 | 568 | portföy 28.4% |
| Maliyet: sabit_fonlama | 21721 | -0.006 | -0.8 | -141 | portföy -7.7% |

### Sağlık kontrolleri — 4s_tetik

| Test | İşlem | Ort. R | t | Toplam R | Not |
|---|---|---|---|---|---|
| Gerçek veri, getiriler karıştırılmış (tohum 0) | 7401 | -0.031 | -2.6 | -230 | kârlı sembol 36.4% |
| Gerçek veri, getiriler karıştırılmış (tohum 1) | 7454 | -0.044 | -3.6 | -324 | kârlı sembol 18.2% |
| Gerçek veri, getiriler karıştırılmış (tohum 2) | 7403 | -0.041 | -3.4 | -301 | kârlı sembol 22.7% |
| Rastgele yürüyüş (20 seri) | - | -0.043 | - | - | medyan getiri -10.4%, kârlı oran 25.0% |
| Sinyal 1 mum ERKEN (gelecek bilgisi!) | 6873 | 0.528 | 22.3 | 3631 | portföy 446.0% |
| Normal | 7009 | 0.078 | 3.7 | 545 | portföy 28.1% |
| Sinyal 1 mum geç | 7042 | 0.059 | 3.0 | 414 | portföy 20.8% |
| Sinyal 2 mum geç | 7065 | 0.050 | 2.6 | 355 | portföy 17.2% |
| Maliyet: maliyetsiz | 7009 | 0.120 | 5.5 | 840 | portföy 47.0% |
| Maliyet: yalniz_komisyon | 7009 | 0.102 | 4.8 | 715 | portföy 38.7% |
| Maliyet: tam | 7009 | 0.078 | 3.7 | 545 | portföy 28.1% |
| Maliyet: maker_benzeri | 7009 | 0.095 | 4.5 | 663 | portföy 35.3% |
| Maliyet: sabit_fonlama | 7009 | 0.076 | 3.6 | 531 | portföy 27.4% |

### Sağlık kontrolleri — 4s_tetik_btc

| Test | İşlem | Ort. R | t | Toplam R | Not |
|---|---|---|---|---|---|
| Gerçek veri, getiriler karıştırılmış (tohum 0) | 4108 | -0.039 | -2.4 | -159 | kârlı sembol 27.3% |
| Gerçek veri, getiriler karıştırılmış (tohum 1) | 4195 | -0.041 | -2.5 | -171 | kârlı sembol 18.2% |
| Gerçek veri, getiriler karıştırılmış (tohum 2) | 4018 | -0.048 | -3.1 | -194 | kârlı sembol 31.8% |
| Rastgele yürüyüş (20 seri) | - | -0.037 | - | - | medyan getiri -3.9%, kârlı oran 35.0% |
| Sinyal 1 mum ERKEN (gelecek bilgisi!) | 5736 | 0.571 | 20.8 | 3275 | portföy 361.5% |
| Normal | 5781 | 0.095 | 4.0 | 550 | portföy 28.3% |
| Sinyal 1 mum geç | 5810 | 0.078 | 3.4 | 451 | portföy 22.7% |
| Sinyal 2 mum geç | 5828 | 0.069 | 3.1 | 404 | portföy 19.6% |
| Maliyet: maliyetsiz | 5781 | 0.141 | 5.6 | 817 | portföy 45.4% |
| Maliyet: yalniz_komisyon | 5781 | 0.123 | 5.0 | 711 | portföy 38.4% |
| Maliyet: tam | 5781 | 0.095 | 4.0 | 550 | portföy 28.3% |
| Maliyet: maker_benzeri | 5781 | 0.113 | 4.6 | 651 | portföy 34.4% |
| Maliyet: sabit_fonlama | 5781 | 0.096 | 4.0 | 557 | portföy 28.9% |

**Sağlık kontrollerinin yorumu:** (a) karıştırılmış gerçek veri ve rastgele yürüyüşte her varyant zarar ediyor ✓.
(b) Sinyali 1 mum **erken** almak (gelecek bilgisi) sonucu absürt biçimde iyileştiriyor (+0.43…+0.57 R) — motor
gelecek bilgisine duyarlı, normal çalıştırma bunu kullanmıyor; 1–2 mum **geç** almak sonucu kademeli kötüleştiriyor ✓.
(c) Maliyet en büyük düşman: 1s stratejide maliyetsiz +0.054 R → tam maliyetle −0.005 R. Maker (limit emir) benzeri
maliyetle +0.026 R olurdu, ama kırılım girişlerinde limit emirle dolum garanti değildir.
Likidasyon: hiçbir varyantta 0 (stop ≤ likidasyon mesafesinin %50'si kuralı sayesinde; yalnız aşırı boşlukta mümkün).

### Güncel ilk 50 (temel, her sembol kendi geçmişiyle)

Sembol: 50, kârlı sembol oranı: **50.0%**, medyan getiri -0.2%, havuz ort. R 0.004 (21371 işlem), likidasyon 0.


**4s_tetik_btc, güncel ilk 50:** kârlı sembol oranı 64%, medyan getiri 2.0%, havuz ort. R 0.091 (5601 işlem, t 4.4); 2025+ dönemi: +0.040 R (t 1.3). Tablo: raporlar/semboller_guncel50_4s_tetik_btc.csv

## 4. Yapılan deneyler

Ayrıntı `DENEYLER.md`. Özetle: 8 varyant (temel, 4s tetik, geniş çıkış, hacim filtresi, volatilite filtresi, BTC rejimi,
sadece long, 4s+BTC) aynı doğrulama setiyle (tüm dönem, 7 yıllık dilim, 54'lük ızgara, walk-forward, holdout, 22 sembol)
karşılaştırıldı. Yalnız 4 saatlik tetikli iki varyant kriterleri geçti. Filtreler (hacim, volatilite, BTC) 1s
stratejiyi kurtarmadı. "Sadece long" holdout'ta en iyi görünüyor (+0.034 R) ama 2022–2024'te ağır zarar ettiği için
kriterleri geçemedi — son dönemdeki boğa piyasasının etkisi.

## 5. Bilinen sınırlamalar

* **Hayatta kalma yanlılığı:** semboller bugünkü listeden seçildi; geçmişte listeden çıkan/batan coinler yok. Sonuçlar
  muhtemelen olduğundan iyi görünüyor.
* **Korelasyon:** aynı anda açılan işlemler (ör. piyasa geneli kırılım) birbirinden bağımsız değildir; t-istatistikleri
  belirsizliği olduğundan küçük gösterir.
* **Portföy modeli:** her sembol ayrı alt hesap; gerçek tek hesapta eşzamanlı pozisyonların toplam teminatı ve toplam
  riski (ör. 10 korelasyonlu LONG = ~%10 risk) daha yüksek olabilir.
* **Dolum varsayımları:** stop fiyatı + %0.03 kayma; ani hareketlerde gerçek kayma çok daha büyük olabilir.
  Likidasyon formülü basitleştirilmiştir (kademeli bakım teminatı yok).
* **Canlı test:** bu çalışmanın yapıldığı sunucudan `fapi.binance.com` erişilemedi (HTTP 451, bölge kısıtı). Canlı
  tarayıcı, pano ve pozisyon takibi gerçek Binance arşiv verisinin hızlandırılmış tekrarıyla (`--demo`) uçtan uca
  test edildi; REST/WebSocket bağlantısı kullanıcının bilgisayarında ilk çalıştırmada doğrulanmalıdır.
* Canlı geçmiş sinyal sonuçlarında fonlama sabit (%0.01/8s, iki yönde maliyet) varsayılır.
* Türev verisi: arşivdeki 5 dk anlık görüntülerin zaman anlamı ile canlı REST yanıtınınki aynı kabul edildi (canlıda
  burada doğrulanamadı); mum için yalnızca kapanıştan ≥5 dk önceki görüntü kullanılır. Kısa geçmişli semboller için
  canlıda açık pozisyon verisi yoksa filtre sinyali engeller (güvenli taraf).
