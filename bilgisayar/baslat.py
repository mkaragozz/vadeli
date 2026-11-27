"""Tek tıkla başlatıcı (baslat.bat / baslat.command bunu çalıştırır).

İlk açılışta: sanal ortam (.venv) kurar, paketleri yükler, hesap büyüklüğünü sorar ve config.toml'a yazar.
Sonraki açılışlarda: yalnızca gerekirse paketleri günceller ve tarayıcıyı başlatır, panoyu tarayıcıda açar.
Bu dosya yalnızca Python'un standart kütüphanesini kullanır (sistem Python'u ile çalışır).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

KOK = Path(__file__).resolve().parent
VENV = KOK / ".venv"
WINDOWS = os.name == "nt"
VPY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
DAMGA = VENV / ".kurulum_damgasi"
CONFIG = KOK / "config.toml"
ADRES = "http://127.0.0.1:{port}"


def yaz(m: str = "") -> None:
    print(m, flush=True)


def dur(kod: int = 1) -> None:
    """Pencere hemen kapanmasın, kullanıcı mesajı okuyabilsin."""
    try:
        input("\nKapatmak için Enter'a basın...")
    except EOFError:
        pass
    sys.exit(kod)


def surum_kontrol() -> None:
    if sys.version_info < (3, 10):
        yaz(f"Python {sys.version.split()[0]} çok eski. Python 3.11 veya üstü gerekli.")
        yaz("https://www.python.org/downloads/ adresinden kurun (Windows'ta 'Add python.exe to PATH' kutusunu işaretleyin).")
        webbrowser.open("https://www.python.org/downloads/")
        dur()


def kurulum() -> None:
    gerek = (KOK / "requirements.txt").read_bytes()
    ozet = hashlib.sha256(gerek + sys.version.encode()).hexdigest()
    if VPY.exists() and DAMGA.exists() and DAMGA.read_text().strip() == ozet:
        return
    if not VPY.exists():
        yaz("İlk kurulum: sanal ortam oluşturuluyor (bir kez, ~1 dk)...")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        except subprocess.CalledProcessError:
            yaz("Sanal ortam oluşturulamadı. Linux'ta: sudo apt install python3-venv")
            dur()
    yaz("Gerekli paketler yükleniyor (birkaç dakika sürebilir)...")
    try:
        subprocess.run([str(VPY), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"], check=False)
        subprocess.run([str(VPY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(KOK / "requirements.txt")], check=True)
    except subprocess.CalledProcessError:
        yaz("\nPaketler yüklenemedi. İnternet bağlantınızı kontrol edip tekrar deneyin.")
        dur()
    DAMGA.write_text(ozet)
    yaz("Kurulum tamam.\n")


def ilk_ayar() -> None:
    if CONFIG.exists():
        return
    metin = (KOK / "config.example.toml").read_text(encoding="utf-8")
    yaz("İlk ayar: hesap büyüklüğünüz (USDT). Daha sonra panodaki Ayarlar ekranından değiştirebilirsiniz.")
    while True:
        try:
            g = input("Hesap büyüklüğü [1000]: ").strip().replace(",", ".") or "1000"
        except EOFError:
            g = "1000"
        try:
            hesap = float(g)
            if 10 <= hesap <= 10_000_000:
                break
        except ValueError:
            pass
        yaz("Lütfen 10 ile 10.000.000 arasında bir sayı girin.")
    metin = re.sub(r"(?m)^hesap = [0-9.]+", f"hesap = {hesap:.2f}", metin, count=1)
    CONFIG.write_text(metin, encoding="utf-8")
    yaz(f"Kaydedildi: config.toml (hesap = {hesap:.2f} USDT)\n")


def port_oku() -> int:
    m = re.search(r"(?m)^port\s*=\s*(\d+)", CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else None
    return int(m.group(1)) if m else 8000


def panoyu_ac(port: int) -> None:
    """Sunucu hazır olunca varsayılan tarayıcıda panoyu aç."""
    url = ADRES.format(port=port)
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/oturum", timeout=2)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(1)


def main() -> None:
    os.chdir(KOK)
    surum_kontrol()
    kurulum()
    ilk_ayar()
    port = port_oku()
    yaz("=" * 70)
    yaz("Vadeli Sinyal Tarayıcı başlıyor. Pano birazdan tarayıcıda açılacak:")
    yaz(f"  {ADRES.format(port=port)}")
    yaz("Bu pencere açık kaldıkça tarama sürer. Durdurmak için: Ctrl + C (veya pencereyi kapatın).")
    yaz("Sistem emir göndermez. Kaldıraç zarar riskini büyütür; stop'u borsada girin.")
    yaz("=" * 70)
    threading.Thread(target=panoyu_ac, args=(port,), daemon=True).start()
    ek = sys.argv[1:]  # ör. baslat.bat --host 100.x.y.z
    try:
        kod = subprocess.call([str(VPY), str(KOK / "tarayici.py"), "tara", *ek])
    except KeyboardInterrupt:
        kod = 0
    if kod not in (0, -2, 130, 3221225786):  # 3221225786 = Windows'ta Ctrl+C
        yaz(f"\nProgram bir hatayla kapandı (kod {kod}). Yukarıdaki mesajın ekran görüntüsünü alın.")
        dur(kod)


if __name__ == "__main__":
    main()
