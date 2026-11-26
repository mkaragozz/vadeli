# Vadeli Sinyal Tarayıcı — telefon sürümü

**Aç:** https://mkaragozz.github.io/vadeli/ → telefonda *Ana Ekrana Ekle* (iPhone: Paylaş ⬆︎; Android: Uygulamayı yükle).

Binance USDT-M vadeli piyasası için sinyal tarayıcı. Veriyi doğrudan Binance'in herkese açık uç noktalarından okur;
**API anahtarı istemez, emir göndermez**. Pozisyon kayıtları yalnızca telefonda (tarayıcı belleğinde) saklanır.

> Kaldıraç zarar riskini büyütür; stop'u borsada girin. Yatırım tavsiyesi değildir.

Kaynak kod, testler (Python ile eşdeğerlik testi dahil), gerçek veri doğrulaması ve bilgisayar sürümü:
[mkaragozz/kitap-notlari → vadeli-tarayici](https://github.com/mkaragozz/kitap-notlari/tree/main/vadeli-tarayici)
(`RAPOR.md`, `DENEYLER.md`). Bu depo yalnızca yayınlanan kopyadır; düzenleme orada yapılıp
`python3 mobil_yayinla.py` ile buraya kopyalanır.

Grafik: TradingView Lightweight Charts™ (Apache 2.0, `lib/`).
