# BORSA VERİ ANALİSTİ — kripto borsa verisi analizi ve vadeli sinyal tarayıcı (Binance)

Binance USDT-M perpetual vadeli piyasasında hacme göre ilk 50 sözleşmeyi izleyen, LONG/SHORT sinyallerini
ve risk/kaldıraç hesabını gösteren sistem: **backtest + doğrulama**, **canlı tarayıcı**, **telefon ve bilgisayardan
açılan web panosu (PWA)**.

> ⚠️ **Kaldıraç zarar riskini büyütür; stop'u borsada gir. Yatırım tavsiyesi değildir.**
> **Doğrulama sonucu (özet):** şartnamedeki 1s-tetik strateji gerçek veride maliyetlerden sonra kenar göstermedi.
> Varsayılan olarak doğrulamayı geçen **4s tetik + BTC rejim filtresi + açık pozisyon teyidi** kullanılır. Bu varyantın
> 2025-2026 sonucu umut verici ama istatistiksel olarak kesin değil. Ayrıntı: `RAPOR.md`.
>
> **Veri kaynakları:** Binance (mumlar, fonlama, açık pozisyon, long/short, taker — CoinGlass'taki Binance verisiyle aynı
> ham veri), CoinGecko (piyasa geneli, ısı haritası), isteğe bağlı CoinMarketCap ve CoinGlass anahtarları.
> TradingView'den veri **çekilmez** (resmi API yok, kazıma kullanım şartlarına aykırı).
>
> Sistem **hiçbir koşulda emir göndermez** ve **API anahtarı istemez/kullanmaz**; yalnızca Binance'in herkese açık
> uç noktalarından veri okur. Strateji sonuçları için önce [`RAPOR.md`](RAPOR.md)'yi okuyun.

## İçindekiler
1. [Kurulum](#1-kurulum)
2. [Hızlı başlangıç](#2-hızlı-başlangıç)
3. [Backtest ve doğrulama](#3-backtest-ve-doğrulama)
4. [Pano (ekranlar)](#4-pano)
5. [Telefondan kullanım ve uzaktan erişim](#5-telefondan-kullanım-ve-uzaktan-erişim) — bilgisayar (Tailscale) / VPS (Caddy + parola)
6. [Bildirimler (Telegram, Web Push)](#6-bildirimler)
7. [Yapılandırma](#7-yapılandırma)
8. [Mimari ve dosyalar](#8-mimari-ve-dosyalar)
9. [Testler](#9-testler)
10. [Sorun giderme](#10-sorun-giderme)

---

## 0. Telefon sürümü (kurulumsuz, tek bağlantı)

**https://mkaragozz.github.io/vadeli/** — telefonda açın, *Ana Ekrana Ekle* deyin.

* Bilgisayar gerekmez: telefon veriyi doğrudan Binance'in herkese açık uç noktalarından okur (anahtar yok, emir yok).
* Bilgisayar sürümüyle **aynı strateji kodu** (depo kökündeki `strateji.js`; telefon uygulaması bu deponun kökünden yayınlanır, Python ile eşdeğerlik testi:
  `tests/test_mobil_esdeger.py`): 4s kırılım, BTC rejimi, açık pozisyon teyidi, aynı risk/kaldıraç hesabı.
* Sınırlar: yalnızca uygulama **açıkken** tarar (kapalıyken bildirim yok); pozisyon kayıtları yalnızca o telefonda;
  backtest/geçmiş istatistik ekranı yok. 7/24 tarama ve Telegram için aşağıdaki bilgisayar sürümünü kullanın.
* Binance bulunduğunuz bölgeden vadeli veriye izin vermiyorsa (HTTP 451) telefon sürümü veri alamaz.

## 1. Kurulum

Gerekenler: **Python 3.10+** (3.11+ önerilir), internet. Windows, macOS ve Linux'ta çalışır.

### En kolay yol: tek tıkla başlat
1. Python'u https://www.python.org/downloads/ adresinden kurun. **Windows'ta ilk ekrandaki "Add python.exe to PATH"
   kutusunu işaretleyin.**
2. `vadeli-tarayici` klasöründe:
   * **Windows:** `baslat.bat` dosyasına çift tıklayın. "Windows bilgisayarınızı korudu" uyarısı çıkarsa
     *Ek bilgi → Yine de çalıştır*.
   * **Mac:** `baslat.command` dosyasına **sağ tıklayıp → Aç** deyin (ilk seferde "bilinmeyen geliştirici" uyarısı için).
     Sonraki seferlerde çift tıklamak yeterli.
3. İlk açılışta kurulum birkaç dakika sürer ve hesap büyüklüğünüz sorulur (sonra `config.toml`'dan veya panodaki
   Ayarlar'dan değişir). Pano tarayıcıda kendiliğinden açılır. Siyah pencere açık kaldıkça tarama sürer.
4. Telefondan erişim için (Tailscale, bkz. §5A): `baslat.bat --host 100.x.y.z` veya `config.toml` içinde
   `host = "100.x.y.z"` yazın.

### Elle kurulum

```bash
cd vadeli-tarayici
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml        # isteğe bağlı; yoksa varsayılanlar kullanılır
```

## 2. Hızlı başlangıç

```bash
python tarayici.py tara --hesap 1000
```

* Terminalde her 1 saatlik mum kapanışından ~5 sn sonra tarama yapılır (pozisyonlar her saat değerlendirilir); varsayılan stratejide yeni sinyaller 4 saatlik mum kapanışlarında (UTC 00, 04, 08, …) oluşur. Yeni sinyalde zil çalar.
* Pano: **http://127.0.0.1:8000** (yalnızca bu bilgisayardan erişilebilir).
* İlk açılışta her sembol için ~3000 saatlik geçmiş indirilir (1–2 dk). Sonraki taramalarda yalnızca yeni mumlar
  eklenir; veriler `veri/tarayici.db` (SQLite) içinde saklanır, yeniden başlatınca tekrar indirilmez.
* Canlı akış WebSocket (`wss://fstream.binance.com`) ile gelir; koparsa otomatik yeniden bağlanır. WebSocket'in
  kaçırdığı mum REST ile tamamlanır. REST hatalarında üstel geri çekilme uygulanır; tek sembolün hatası taramayı durdurmaz.
* Her sinyal `sinyaller.csv` dosyasına (zaman, sembol, yön, fiyat, stop, …) ve veritabanına eklenir.

Binance'e bağlanmadan denemek için **demo** (arşivdeki gerçek veriyi hızlandırılmış saatle oynatır, 1 saat = 3 sn):

```bash
python tarayici.py indir --semboller BTCUSDT ETHUSDT SOLUSDT   # demo için biraz arşiv verisi
python tarayici.py tara --demo
```

Diğer bayraklar: `--risk 1 --max-kaldirac 5 --sembol-sayisi 50 --port 8000 --host 127.0.0.1 --pano-yok --sessiz`.

## 3. Backtest ve doğrulama

```bash
python tarayici.py indir --ilk 50                 # hacimce ilk 50 + geçmiş (data.binance.vision arşivi, CSV önbellek)
python tarayici.py backtest                       # tam doğrulama (~10-30 dk; ilk seferde indirme dahil)
python tarayici.py backtest --hizli               # sadece temel strateji, küçük ızgara
python tarayici.py backtest --demo                # sentetik veriyle saniyeler içinde
python tarayici.py backtest --turev               # türev filtre deneyi (açık pozisyon, fonlama, long/short, taker; 2022+)
python tarayici.py backtest --tur2                # tur 2: göreli güç, başabaş stop, günlük tetik, hayatta kalma, tek hesap
python tarayici.py ileri-test                     # ileri test: 2026-11-01'den beri dondurulmuş strateji (arşiv, ~2-5 dk)
```

**İleri test** (`DENEYLER.md` §3): dondurulmuş strateji, hiçbir analizde kullanılmamış veride (2026-11-01'den beri,
22 sembol) Binance arşivinden hesaplanır. Bilgisayarın açık kalmasına bağlı değildir. Tarayıcı açıksa her gün 03 UTC'den
sonra kendiliğinden güncellenir. Panoda **Geçmiş → İleri test**: karar (ERKEN / İZLE / DUR / UYGUN), kümülatif R ve
beklenti bandı. Karar kuralları önceden yazıldı; 100. işlemde ortalama ≤ 0 ise DUR.

Ne yapar (ayrıntı ve sonuçlar: `RAPOR.md`, deneme günlüğü: `DENEYLER.md`):

| Kontrol | Açıklama |
|---|---|
| Gerçek veri | Binance USDT-M **resmi arşivi** (data.binance.vision) 1s mumlar 2020-01'den beri + **gerçek fonlama oranları**; `veri_onbellek/` altına CSV olarak önbelleklenir |
| Metrikler | toplam/yıllık getiri, max düşüş, Sharpe, işlem sayısı, kazanma, profit factor, long/short, çıkış nedenleri, likidasyon, al-tut |
| Dilimli tutarlılık | 2020…2026 her yıl ayrı |
| Parametre sağlamlığı | 54 kombinasyonluk ızgara (giriş 10/20/40/55 × çıkış 5/10/20 × ATR 2/3/4 × EMA 100/200, çıkış<giriş); kârlı kombinasyon oranı ve medyan |
| Walk-forward | 2 yıl eğitimde seç → sonraki yıl görülmemiş veride test (2022–2026) |
| Çoklu sembol | 22 uzun geçmişli sembol + güncel ilk 50, sembol bazında tablo |
| Sağlık | getirileri karıştırılmış gerçek veri, rastgele yürüyüş, ±1 mum kaydırma, maliyet duyarlılığı |
| Alternatifler | 4s tetik, geniş çıkış, hacim/volatilite filtresi, BTC rejimi, sadece long… aynı doğrulama setiyle |

Çıktılar `raporlar/` altındadır (`rapor.json`, CSV'ler, `ozet.md`) ve panonun **Backtest** ekranında görünür.

**Kurallar (backtest = canlı):** sinyal kapanan mumda üretilir, işlem **sonraki mumun açılışında**; kapanmamış mum
hiçbir hesapta kullanılmaz; 4s rejim yalnızca **tamamlanmış** 4s mumdan alınır. Backtest, canlı tarayıcı, pozisyon
takibi ve geçmiş sinyal sonuçları **aynı** `strateji.hazirla` fonksiyonunu ve **aynı** `backtest.PozisyonTakip`
çıkış mantığını kullanır.

## 4. Pano

| Ekran | İçerik |
|---|---|
| **Sinyaller** | Üstte özet şeridi: sonraki mum kapanışına kalan süre, aktif sinyal sayısı, **açık pozisyon / tavan (5)**, ileri test durumu. Her kartta **"Binance'e girilecekler"**: marjin/kaldıraç, emir türü, kopyalanabilir miktar ve stop fiyatı. Doğrulanan 22'lik setin dışındaki coinler **"ana set dışı"** etiketi taşır (bu coinlerde backtest kenarı çok zayıf); "Yalnız ana set" filtresi. Aktif sinyal kartları: yön, sembol, YENİ/devam, fiyat, stop, stop %, kaldıraç, pozisyon $, teminat, likidasyon, risk $, 4s rejim. Filtre: LONG/SHORT, YENİ/devam, min. 24s hacim, sembol arama; sıralama: yenilik/hacim/stop %/risk. Filtreler adres çubuğunda saklanır (yenileyince kaybolmaz). **Yaklaşanlar** sekmesi: kırılıma 0.5 ATR kalanlar. Karta dokununca grafik açılır. |
| **Grafik** | Altında sembolün türev verileri: açık pozisyon ve değişimi, fonlama, long/short oranları, kalabalık z-skoru, taker alım/satım. 1s/4s mumlar, EMA200(4s) rejim çizgisi, giriş kanalı, sinyal işaretleri, giriş/stop/likidasyon çizgileri (açık pozisyonun önerilen stopu dahil). Kütüphane: TradingView Lightweight Charts™ (Apache 2.0) — **yerel dosya**, veri kendi API'mizden (`/api/mumlar?sembol=...&aralik=1h`). |
| **Piyasa** | CoinGecko'dan toplam piyasa değeri, 24s değişim, BTC/ETH dominansı, stabilcoin payı ve ilk 100 coinin **ısı haritası** (1 saat / 24 saat / 7 gün; kutu boyu piyasa değeri, renk değişim). Vadelide olan coine dokununca grafiği açılır. Bilgi amaçlıdır, sinyale girmez. |
| **Pozisyonlarım** | Borsada açtığınız pozisyonu girin (sinyaldeki "Pozisyon aç" formu doldurur). Her 1s kapanışında: gerçekleşmemiş K/Z ve R katı, önerilen takip stopu ("stopu X'e çekin"), **çıkış sinyali** (karşı kanal kırılımı), stop/likidasyon yakınlığı (mesafenin %30'undan az kaldıysa) — ekranda ve bildirimle. Not ekleme, kapatma. **Sistem emir göndermez.** |
| **Geçmiş** | **İleri test** kartı (karar, ilerleme, kümülatif R grafiği, kurallar, işlemler, "Şimdi güncelle"). Altında üretilen her sinyal (zaman, sembol, yön, fiyat, stop, parametre sürümü) ve backtest ile aynı kurallarla simüle edilmiş sonucu (R, süre, çıkış nedeni). Toplam / long / short / sembol bazında istatistik, **canlı ile backtest beklentisi yan yana**. |
| **Backtest** | Varyant karşılaştırması, özkaynak eğrisi, yıllık dilimler, ızgara, walk-forward, sembol tablosu, sağlık kontrolleri; "Yeniden çalıştır" (arka planda, ilerleme gösterir). |
| **Ayarlar** | Hesap, risk %, max kaldıraç, sembol sayısı, bildirim kanalları. Sonraki taramada devreye girer. |

Üst çubukta her zaman: canlı bağlantı göstergesi (yeşil = bağlı ve veri taze, sarı = veri gecikmeli, kırmızı = bağlantı yok),
son tarama zamanı, sağlıklı veri sayısı ve son mum gecikmesi. Arayüz Server-Sent Events ile anlık güncellenir.

**Kaldıraç neden riski değiştirmez:** Pozisyon büyüklüğü = (hesap × risk %) ÷ stop mesafesi. Kaldıraç yalnızca bu
pozisyon için borsaya yatırılan teminatı belirler. Kaldıraç, stop mesafesi likidasyon mesafesinin en fazla %50'si olacak
şekilde ve kullanıcı tavanıyla (varsayılan 5x) sınırlanır; böylece stop her zaman likidasyondan önce gelir.

## 5. Telefondan kullanım ve uzaktan erişim

**Telefonda Python çalıştırılmaz.** Tek bir arka uç (tarayıcı + API + veritabanı) bilgisayarınızda veya 7/24 açık bir
sunucuda (VPS) çalışır; bilgisayar ve telefon aynı web arayüzüne tarayıcıdan bağlanır.
Pano pozisyon bilgisi içerdiği için **internete şifresiz açılmaz**: dış bir adrese parolasız bağlanmaya çalışırsanız
program başlamayı reddeder.

### 5A. Telefonda uygulama olarak (önerilen, tek dokunuşla açılır)

Port açmadan, yalnızca **sizin cihazlarınızın** erişebildiği güvenli HTTPS adresi (Tailscale).

**Bir kez yapılır:**
1. **Bilgisayara** Tailscale kurun ve giriş yapın: https://tailscale.com/download
2. **Telefona** Tailscale uygulamasını kurun (App Store / Google Play), **aynı hesapla** giriş yapın.
3. Bilgisayarda `baslat.bat` / `baslat.command` ile programı başlatın. Program Tailscale'i kendisi bulur,
   panoyu `https://<bilgisayarınız>.<ağınız>.ts.net` adresinden yayınlar ve siyah pencerede bir **QR kodu** gösterir
   (aynı kod panoda **Ayarlar → 📱 Telefona kur** kartında da var).
   * İlk seferde Tailscale "HTTPS'i etkinleştir" onayı isteyebilir: açılan sayfada onaylayın ve programı yeniden başlatın.
4. Telefonun kamerasıyla QR kodu okutun → pano açılır.
5. **iPhone:** Safari'de Paylaş ⬆︎ → *Ana Ekrana Ekle*. **Android:** Chrome'da *Uygulamayı yükle* (veya ⋮ → *Ana ekrana ekle*).

**Sonra:** ana ekrandaki **Vadeli** simgesine dokunmanız yeterli; tam ekran, uygulama gibi açılır. Simgeye uzun basınca
Sinyaller / Pozisyonlarım / Piyasa kısayolları çıkar (Android). Telefonda Tailscale açık olmalı, bilgisayarda program çalışıyor olmalı.

Notlar:
* Pano bilgisayarda 127.0.0.1'de kalır; Tailscale yalnızca sizin Tailscale ağınızdaki cihazlara iletir (internete açılmaz,
  `funnel` kullanılmaz). İstemezseniz `config.toml` → `telefon = "kapali"`.
* Bilgisayar uykudayken tarama durur. 7/24 için uykuyu kapatın veya VPS kullanın (5B).
* Elle: `tailscale serve --bg http://127.0.0.1:8000` aynı işi yapar.

### 5B. VPS (7/24) + HTTPS (Caddy) + parola

1. Bir Linux VPS kiralayın. **Önemli:** Binance bazı ülkelerden erişimi engeller (ör. ABD IP'leri `451` hatası alır).
   Sunucuyu Binance'in hizmet verdiği bir bölgede seçin.
2. Bir alan adını (ör. `tarama.ornek.com`) VPS'in IP'sine yönlendirin (DNS A kaydı).
3. Kurulum:
   ```bash
   sudo apt update && sudo apt install -y python3-venv git caddy
   git clone <bu depo> && cd kitap-notlari/vadeli-tarayici
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp config.example.toml config.toml   # [pano] guvenli_cerez = true yapın
   ```
4. Güçlü bir parola belirleyin (en az 12 karakter; koda/dosyaya yazılmaz, ortam değişkeni):
   ```bash
   sudo mkdir -p /etc/vadeli && sudo sh -c 'umask 077; printf "PANO_PAROLA=%s\n" "$(openssl rand -base64 24)" > /etc/vadeli/ortam'
   sudo cat /etc/vadeli/ortam      # parolayı bir kez görüp parola yöneticinize kaydedin
   ```
5. systemd servisi (`/etc/systemd/system/vadeli.service`, örnek: `dagitim/vadeli.service`):
   ```ini
   [Service]
   User=vadeli
   WorkingDirectory=/opt/vadeli-tarayici
   EnvironmentFile=/etc/vadeli/ortam
   ExecStart=/opt/vadeli-tarayici/.venv/bin/python tarayici.py tara --host 127.0.0.1 --port 8000 --sessiz
   Restart=always
   ```
   `sudo systemctl enable --now vadeli`
6. Caddy (otomatik Let's Encrypt sertifikası) — `/etc/caddy/Caddyfile` (örnek: `dagitim/Caddyfile`):
   ```
   tarama.ornek.com {
       encode gzip
       reverse_proxy 127.0.0.1:8000 {
           flush_interval -1
       }
   }
   ```
   `sudo systemctl reload caddy`. Güvenlik duvarında yalnız 22, 80, 443 açık olsun (`sudo ufw allow 22,80,443/tcp && sudo ufw enable`).
   Pano 127.0.0.1'de dinler; dışarıdan yalnızca Caddy üzerinden HTTPS ile erişilir.
7. Telefonda `https://tarama.ornek.com` → parola ile giriş → ana ekrana ekleyin.

Güvenlik özellikleri: parola sabit zamanlı karşılaştırılır; oturum çerezi rastgele 256 bit, HttpOnly, SameSite=Strict,
HTTPS'te Secure; IP başına 15 dakikada 5 hatalı deneme sınırı; durum değiştiren isteklerde köken (CSRF) kontrolü;
CSP ile satır içi betik yasak; tüm veriler arayüzde HTML olarak değil metin olarak basılır; API girdileri doğrulanır.

## 6. Bildirimler

Aynı sembol + yön + mum için bildirim **bir kez** gönderilir. Pozisyon uyarıları: çıkış sinyali, stop güncelleme önerisi,
stop/likidasyon yakınlığı.

### Telegram (birincil, en güvenilir)
1. Telegram'da **@BotFather** → `/newbot` → bot anahtarını alın.
2. Bota bir mesaj yazın, sonra `https://api.telegram.org/bot<ANAHTAR>/getUpdates` adresinden `chat.id` değerini öğrenin.
3. Ortam değişkenleri (koda yazmayın):
   ```bash
   export TG_TOKEN="123456:ABC..."   TG_CHAT="123456789"      # Windows PowerShell: $env:TG_TOKEN="..."
   ```
4. `config.toml` → `telegram = true` veya panoda Ayarlar → Telegram.

### Web Push (isteğe bağlı)
```bash
pip install pywebpush            # py-vapid aracını da kurar
mkdir -p ~/.vadeli && cd ~/.vadeli && vapid --gen         # private_key.pem ve public_key.pem üretir
vapid --applicationServerKey                              # yazdırılan değeri VAPID_PUBLIC_KEY yapın
export VAPID_PRIVATE_KEY="$HOME/.vadeli/private_key.pem"  VAPID_PUBLIC_KEY="<yukarıdaki değer>"  VAPID_SUB="mailto:siz@ornek.com"
```
Panoda Ayarlar → "Bu cihazda Web Push'u etkinleştir". **iPhone/iPad:** Web Push yalnızca Safari'de *Ana Ekrana Ekle* ile
kurulmuş uygulamada ve iOS 16.4+ sürümünde çalışır; ayrıca HTTPS gerekir (Tailscale `serve` veya VPS + Caddy).
Güvenilirlik için Telegram önerilir.

## 7. Yapılandırma

Öncelik: panodaki Ayarlar > CLI bayrakları > `config.toml` > varsayılanlar. Tüm alanlar: `config.example.toml`.

| Ortam değişkeni | Anlamı |
|---|---|
| `PANO_PAROLA` | Pano parolası (dış arayüzde zorunlu, ≥ 12 karakter) |
| `COINGECKO_API_KEY` | İsteğe bağlı CoinGecko demo anahtarı (hız limiti için; anahtarsız da çalışır) |
| `CMC_API_KEY` | İsteğe bağlı CoinMarketCap anahtarı (Piyasa ekranında küresel metrikler) |
| `COINGLASS_API_KEY` | İsteğe bağlı CoinGlass anahtarı (çoklu borsa açık pozisyon) |
| `TG_TOKEN`, `TG_CHAT` | Telegram |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUB` | Web Push |

Loglar: `loglar/tarayici.log` (döngüsel, 5 × 5 MB), `loglar/backtest.log`.

## 8. Mimari ve dosyalar

```
tarayici.py              komut satırı (tara / backtest / indir)
vadeli/veri.py           Binance arşivi + ccxt REST (herkese açık), CSV önbellek, sentetik veri
vadeli/strateji.py       hazirla() — TEK sinyal fonksiyonu; risk_hesapla() — pozisyon/kaldıraç/likidasyon
vadeli/backtest.py       PozisyonTakip (çıkış kuralları), calistir(), tek_sinyal_simule()
vadeli/dogrulama.py      çoklu sembol, dilimler, ızgara, walk-forward
vadeli/rapor_uret.py     tam doğrulama + raporlar/
vadeli/borsa.py          BinanceBorsa (REST + WebSocket), DemoBorsa
vadeli/canli.py          Tarayici: artımlı veri, tarama, pozisyon değerlendirme, geçmiş sonuçlar
vadeli/db.py             SQLite (sinyaller, pozisyonlar, mum önbelleği, ayarlar, bildirim tekrarı)
vadeli/pano.py           FastAPI: API + SSE + giriş/güvenlik
vadeli/bildirim.py       Telegram, Web Push
vadeli/terminal.py       renkli tablo + zil
static/                  PWA arayüzü (HTML/CSS/JS, manifest, service worker, yerel lightweight-charts)
tests/                   pytest
dagitim/                 systemd ve Caddy örnekleri
```

## 9. Testler

```bash
python -m pytest -q
```
Kapsam: gelecek verisi değiştirilince geçmiş sinyallerin değişmemesi, kesik veri = tam veri (canlı = backtest),
4s hizalaması (yalnız tamamlanmış 4s mum), kanalın `shift(1)` ile mevcut mumu içermemesi, girişin sonraki açılışta
dolması, kayma yönü, stop/boşluk/likidasyon mantığı, takip stopunun yalnız lehine gitmesi, fonlama zamanlaması ve işareti,
kaldıraç kuralı, geçmiş sinyal simülasyonu = backtest işlemi, rastgele yürüyüşte kâr olmaması, gelecek bilgisi
kaydırmasının sahte kâr üretmesi (motorun duyarlılık kontrolü), API girişi/deneme sınırı/CSRF/girdi doğrulama,
kodda emir/anahtar çağrısı bulunmaması.

## 10. Sorun giderme

| Belirti | Çözüm |
|---|---|
| `451 Service unavailable from a restricted location` | Binance bulunduğunuz/sunucunun bölgesine hizmet vermiyor. Başka bölgede sunucu kullanın. (Arşiv `data.binance.vision` genelde her yerden erişilebilir: backtest çalışır.) |
| `GÜVENLİK: ... Parolasız açılamaz` | Dış arayüzde `PANO_PAROLA` ayarlayın veya Tailscale IP'si / 127.0.0.1 kullanın. |
| Üst çubukta sarı nokta | Veri gecikmeli: internet/Binance bağlantısını ve `loglar/tarayici.log`'u kontrol edin. |
| Telefonda güncelleme görünmüyor | Sayfayı aşağı çekip yenileyin; service worker ağ öncelikli çalışır. |
| Web Push iPhone'da çalışmıyor | Ana ekrana eklenmiş PWA + iOS 16.4+ + HTTPS gerekir; Telegram'ı kullanın. |
