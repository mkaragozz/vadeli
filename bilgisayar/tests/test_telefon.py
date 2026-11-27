"""Telefon erişimi: Tailscale algılama, serve, HTTPS onayı, QR üretimi (sahte tailscale komutuyla)."""
from __future__ import annotations

import os
import stat
import sys

import pytest

from vadeli import telefon

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="sahte kabuk betiği")


def _sahte(tmp_path, monkeypatch, status: str, serve: str, serve_kod: int = 0):
    y = tmp_path / "tailscale"
    y.write_text(f"""#!/bin/bash
case "$1" in
  status) echo '{status}';;
  serve) echo "{serve}"; exit {serve_kod};;
esac
""")
    y.chmod(y.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("PANO_TELEFON_URL", raising=False)


CALISAN = '{"BackendState":"Running","Self":{"DNSName":"pc.tail1.ts.net.","TailscaleIPs":["100.1.2.3"]}}'


def test_kurulu_degil(monkeypatch):
    monkeypatch.setattr(telefon, "tailscale_yolu", lambda: None)
    s = telefon.yayinla(8000)
    assert s["url"] is None and "kurulu değil" in s["mesaj"]


def test_oturum_kapali(tmp_path, monkeypatch):
    _sahte(tmp_path, monkeypatch, '{"BackendState":"NeedsLogin"}', "")
    s = telefon.yayinla(8000)
    assert s["url"] is None and "giriş" in s["mesaj"]


def test_basarili_https_adresi(tmp_path, monkeypatch):
    _sahte(tmp_path, monkeypatch, CALISAN, "Serve started and running in the background.")
    s = telefon.yayinla(8123)
    assert s["url"] == "https://pc.tail1.ts.net"
    svg = telefon.qr_svg(s["url"])
    assert svg.startswith("<svg") and "script" not in svg
    assert "█" in telefon.qr_terminal(s["url"]) or "▀" in telefon.qr_terminal(s["url"])


def test_https_onayi_gerekli(tmp_path, monkeypatch):
    _sahte(tmp_path, monkeypatch, CALISAN, "Serve is not enabled on your tailnet. To enable, visit: https://login.tailscale.com/f/serve?node=abc",
           serve_kod=1)
    monkeypatch.setattr(telefon.webbrowser, "open", lambda u: None)
    s = telefon.yayinla(8000)
    assert s["url"] is None and s["onay_url"].startswith("https://login.tailscale.com")


def test_kapali_mod():
    assert telefon.hazirla(8000, "kapali")["url"] is None
