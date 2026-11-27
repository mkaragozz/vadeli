# BORSA VERİ ANALİSTİ

**Telefonda aç:** https://mkaragozz.github.io/vadeli/ → *Ana Ekrana Ekle* (iPhone: Paylaş ⬆︎; Android: Uygulamayı yükle).

Kripto borsa verisi analizi: en çok düşen/yükselen ve hacim taramaları; 4 saat · günlük ve 3 gün · haftalık
formasyon, destek/direnç ve indikatör sinyalleri (geçmiş isabet oranlarıyla); fiyat alarmları; yapay zekâ skorları;
Binance USDT-M vadeli sinyal tarayıcı. Veri doğrudan Binance'in herkese açık uç noktalarından okunur;
**API anahtarı istemez, emir göndermez**. Kayıtlar yalnızca cihazda saklanır.

> Kaldıraç zarar riskini büyütür; stop'u borsada girin. Yatırım tavsiyesi değildir. Geçmiş isabet geleceği garanti etmez.

## Depo düzeni

| Yer | İçerik |
|---|---|
| Depo kökü (`index.html`, `*.js`, `*.json`, `lib/`) | **Telefon uygulaması** (PWA). GitHub Pages buradan yayınlar. Bilgisayar panosu da aynı ortak modülleri (`analiz.js`, `tarama.js`, `formasyon.js`, `meta.js`, `strateji.js`, `tema.js`) kullanır. |
| [`bilgisayar/`](bilgisayar/) | **Bilgisayar sürümü** (7/24 tarama, pano, Telegram), araştırma kodu (`vadeli/`), testler (`tests/`), raporlar (`raporlar/`, [`RAPOR.md`](bilgisayar/RAPOR.md), [`DENEYLER.md`](bilgisayar/DENEYLER.md)). Kurulum: [`bilgisayar/README.md`](bilgisayar/README.md); Windows'ta `baslat.bat`, Mac'te `baslat.command`. |

Testler (`cd bilgisayar && python -m pytest`) telefon kodunun (JavaScript) Python araştırma koduyla aynı sonucu verdiğini
de doğrular. Geçmiş veri doğrulaması için arşiv verisi `bilgisayar/veri_onbellek/` altına indirilir (depoya girmez).

Önceki geçmiş: proje `mkaragozz/kitap-notlari` deposunun `vadeli-tarayici/` klasöründe başladı ve 2026-11-27'de buraya taşındı.

Grafik: TradingView Lightweight Charts™ (Apache 2.0, `lib/`). Başlık yazı tipi: Exo 2 (SIL Open Font License, `lib/`).
Tablo modelleri (araştırma): TabICL (BSD-3), TabDPT (Apache-2.0), Mitra (Apache-2.0).
