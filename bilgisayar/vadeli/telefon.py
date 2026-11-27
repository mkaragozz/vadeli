"""Telefondan tek dokunuşla erişim: Tailscale ile güvenli HTTPS adresi + QR kodu.

Neden Tailscale `serve`?
  * Pano 127.0.0.1'de kalır (internete açık port yok, parola gerekmez).
  * Tailscale, panoyu yalnızca kullanıcının kendi cihazlarının görebildiği https://<bilgisayar>.<ağ>.ts.net adresinden
    geçerli sertifikayla yayınlar. HTTPS, telefonda tam uygulama kurulumu (ana ekran, tam ekran, bildirim) için şarttır.
  * `funnel` (internete açma) KULLANILMAZ.
"""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)
INDIR = "https://tailscale.com/download"


def tailscale_yolu() -> str | None:
    y = shutil.which("tailscale")
    if y:
        return y
    adaylar = {"Windows": [r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"],
               "Darwin": ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale",
                          "/opt/homebrew/bin/tailscale"]}.get(platform.system(), [])
    return next((a for a in adaylar if Path(a).exists()), None)


def _calistir(args: list[str], zaman_asimi: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=zaman_asimi)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        cikti = (e.stdout or b"").decode(errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -1, cikti
    except OSError as e:
        return -2, str(e)


def durum() -> dict:
    """{'kurulu', 'bagli', 'dns', 'ip', 'mesaj'}"""
    ts = tailscale_yolu()
    if not ts:
        return {"kurulu": False, "bagli": False, "mesaj": f"Tailscale kurulu değil ({INDIR})."}
    kod, cikti = _calistir([ts, "status", "--json"])
    try:
        st = json.loads(cikti[cikti.index("{"):]) if "{" in cikti else {}
    except ValueError:
        st = {}
    if st.get("BackendState") != "Running":
        return {"kurulu": True, "bagli": False, "mesaj": "Tailscale kurulu ama oturum açık değil: Tailscale uygulamasından giriş yapın."}
    self_ = st.get("Self") or {}
    dns = (self_.get("DNSName") or "").rstrip(".")
    ips = self_.get("TailscaleIPs") or []
    return {"kurulu": True, "bagli": True, "dns": dns, "ip": next((i for i in ips if ":" not in i), None), "ts": ts}


def yayinla(port: int) -> dict:
    """Panoyu Tailnet'e HTTPS olarak yayınla. Döner: {'url' | None, 'mesaj'}"""
    d = durum()
    if not d.get("bagli"):
        return {"url": None, **d}
    ts, hedef = d["ts"], f"http://127.0.0.1:{port}"
    # Yeni sürüm sözdizimi (1.52+), olmazsa eski sözdizimi
    for args in ([ts, "serve", "--bg", hedef], [ts, "serve", "--bg", str(port)], [ts, "serve", "https", "/", hedef]):
        kod, cikti = _calistir(args, 25)
        kucuk = cikti.lower()
        if "login.tailscale.com" in cikti or ("not enabled" in kucuk and "https" in kucuk):
            onay = next((w for w in cikti.split() if w.startswith("https://login.tailscale.com")), None)
            if onay:
                try:
                    webbrowser.open(onay)
                except Exception:
                    pass
            return {"url": None, **d, "onay_url": onay,
                    "mesaj": "Tailscale ağınızda HTTPS henüz açık değil. Açılan sayfada onaylayın"
                             + (f" ({onay})" if onay else "") + ", sonra programı yeniden başlatın."}
        if kod == 0:
            url = f"https://{d['dns']}" if d.get("dns") else None
            return {"url": url, **d, "mesaj": "Telefon adresi hazır (yalnızca Tailscale'e bağlı cihazlarınız erişebilir)."}
    log.warning("tailscale serve başarısız: %s", cikti[-300:])
    return {"url": None, **d, "mesaj": "Tailscale serve çalıştırılamadı: " + cikti.strip()[-200:]}


def qr_terminal(metin: str) -> str:
    try:
        import segno
    except ImportError:
        return ""
    b = io.StringIO()
    segno.make(metin, error="m").terminal(out=b, compact=True)
    return b.getvalue()


def qr_svg(metin: str) -> str | None:
    try:
        import segno
    except ImportError:
        return None
    b = io.BytesIO()
    segno.make(metin, error="m").save(b, kind="svg", scale=6, border=2, dark="#000000", light="#ffffff", xmldecl=False)
    return b.getvalue().decode()


def hazirla(port: int, mod: str = "otomatik") -> dict:
    """Başlangıçta çağrılır. Telefon adresini ve QR'ı terminale basar; sonucu döndürür."""
    if mod == "kapali":
        return {"url": None, "mesaj": "Telefon erişimi kapalı (config: telefon = \"kapali\")."}
    if os.environ.get("PANO_TELEFON_URL"):  # elle verilmiş adres (ör. VPS alan adı)
        sonuc = {"url": os.environ["PANO_TELEFON_URL"], "mesaj": "Telefon adresi (PANO_TELEFON_URL)."}
    else:
        sonuc = yayinla(port)
    if sonuc.get("url"):
        print("\n📱 TELEFONDAN AÇMAK İÇİN: telefon kamerasıyla bu kodu okutun (telefonda Tailscale açık olmalı)")
        print(qr_terminal(sonuc["url"]) + f"   {sonuc['url']}\n   Açılınca: iPhone → Paylaş → Ana Ekrana Ekle · Android → Uygulamayı yükle\n", flush=True)
    else:
        print(f"\n📱 Telefon erişimi: {sonuc.get('mesaj')}\n   Kurulum: README → 'Telefondan kullanım'. Panoda Ayarlar → Telefona kur.\n", flush=True)
    return sonuc
