"""Terminal çıktısı: renkli sinyal tablosu, yeni sinyalde zil."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from .bildirim import UYARI

YESIL, KIRMIZI, SARI, GRI, KALIN, SIFIR = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m"
if os.name == "nt":
    os.system("")  # Windows terminalinde ANSI renklerini etkinleştir


def _f(x: float) -> str:
    return f"{x:.6g}"


def tablo_yaz(tarayici, yeni: list[dict]) -> None:
    d = tarayici.durum
    zaman = d.get("sanal_saat") or datetime.now(timezone.utc).isoformat()
    satirlar = [f"\n{KALIN}=== Tarama {zaman[:16].replace('T', ' ')} UTC — {d['sembol']} sembol, "
                f"sağlıklı veri {d['saglikli_sembol']}/{d['sembol']}, {d['tarama_suresi']}s ==={SIFIR}"]
    if tarayici.aktif:
        satirlar.append(f"{'YÖN':6} {'SEMBOL':14} {'ETİKET':6} {'FİYAT':>12} {'STOP':>12} {'STOP%':>6} {'KAL':>4} "
                        f"{'POZ$':>8} {'TEM$':>7} {'LİKİD.':>12} {'RİSK$':>6} 4s")
        for x in sorted(tarayici.aktif, key=lambda z: (not z["yeni"], -z["hacim24"])):
            renk = YESIL if x["yon"] == "LONG" else KIRMIZI
            etiket = f"{SARI}YENİ{SIFIR}  " if x["yeni"] else f"{GRI}devam{SIFIR} "
            satirlar.append(f"{renk}{x['yon']:6}{SIFIR} {x['sembol']:14} {etiket} {_f(x['fiyat']):>12} {_f(x['stop']):>12} "
                            f"{x['stop_yuzde']:6.2f} {x['kaldirac']:4.0f} {x['notional']:8.0f} {x['teminat']:7.0f} "
                            f"{_f(x['likidasyon']):>12} {x['risk_usdt']:6.2f} {'+' if x['rejim'] > 0 else '-'}")
    else:
        satirlar.append(f"{GRI}Aktif sinyal yok.{SIFIR}")
    if tarayici.yaklasan:
        satirlar.append(f"{GRI}Yaklaşan (0.5 ATR kala): " + ", ".join(f"{x['sembol']} {x['yon']}" for x in tarayici.yaklasan[:15]) + SIFIR)
    for p in tarayici.db.pozisyonlar(acik=True):
        r = f"{p['r']:.2f}R" if p.get("r") is not None else "-"
        satirlar.append(f"{KALIN}Pozisyon #{p['id']} {p['yon']} {p['sembol']}{SIFIR}: {r}  {p.get('degerlendirme') or ''}")
    satirlar.append(f"{SARI}{UYARI}{SIFIR}")
    if any(x["yeni"] for x in yeni) and tarayici.cfg.zil:
        satirlar.append("\a")
    print("\n".join(satirlar), flush=True)
    sys.stdout.flush()
