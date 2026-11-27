#!/usr/bin/env python3
"""Binance USDT-M vadeli sinyal tarayıcı — komut satırı.

  python tarayici.py tara --hesap 1000          canlı tarayıcı + pano (http://127.0.0.1:8000)
  python tarayici.py tara --demo                 Binance'e bağlanmadan, arşiv verisini hızlı tekrar oynatarak
  python tarayici.py backtest                    gerçek veriyle tam doğrulama, raporlar/ altına yazar
  python tarayici.py backtest --demo             sentetik veriyle hızlı deneme
  python tarayici.py indir --semboller BTCUSDT ETHUSDT    geçmiş veriyi önbelleğe indir
  python tarayici.py ileri-test                  ileri test: 2026-11-01'den beri dondurulmuş strateji (arşiv verisi)

Sistem hiçbir koşulda emir göndermez ve API anahtarı kullanmaz.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))


def _log_kur(seviye: str = "INFO", dosya: Path | None = None) -> None:
    from logging.handlers import RotatingFileHandler

    isleyiciler: list[logging.Handler] = []
    if dosya:
        dosya.parent.mkdir(parents=True, exist_ok=True)
        isleyiciler.append(RotatingFileHandler(dosya, maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    konsol = logging.StreamHandler()
    konsol.setLevel(logging.WARNING)
    isleyiciler.append(konsol)
    logging.basicConfig(level=getattr(logging, seviye), handlers=isleyiciler,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.ERROR)  # paralel indirmede "pool is full" gürültüsü


def main(argv: list[str] | None = None) -> int:
    for akis in (sys.stdout, sys.stderr):  # Windows konsolunda Türkçe karakter / QR kodu hata vermesin
        try:
            akis.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="tarayici.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)

    t = alt.add_parser("tara", help="canlı tarayıcı + web panosu")
    t.add_argument("--config", type=Path, default=KOK / "config.toml")
    t.add_argument("--hesap", type=float, help="hesap büyüklüğü (USDT)")
    t.add_argument("--risk", type=float, help="işlem başına risk %%")
    t.add_argument("--max-kaldirac", type=float)
    t.add_argument("--sembol-sayisi", type=int)
    t.add_argument("--host", help="varsayılan 127.0.0.1 (yalnızca bu bilgisayar)")
    t.add_argument("--port", type=int)
    t.add_argument("--demo", action="store_true", help="Binance yerine arşiv/sentetik verinin hızlı tekrarı")
    t.add_argument("--demo-hiz", type=float, default=3.0, help="demo: bir 1s mum kaç saniyede (varsayılan 3)")
    t.add_argument("--pano-yok", action="store_true", help="sadece terminal")
    t.add_argument("--sessiz", action="store_true", help="terminal tablosu basma")

    b = alt.add_parser("backtest", help="gerçek veriyle doğrulama raporu")
    b.add_argument("--demo", action="store_true", help="sentetik veri (hızlı)")
    b.add_argument("--hizli", action="store_true", help="sadece temel varyant, küçük ızgara")
    b.add_argument("--semboller", nargs="*")
    b.add_argument("--bitis", default="2026-10", help="son tam ay (YYYY-MM)")
    b.add_argument("--izgara", nargs="*", default=None, help="ızgara + walk-forward yapılacak varyantlar (varsayılan: hepsi)")
    b.add_argument("--turev", action="store_true", help="türev konumlanma filtresi deneyi (açık pozisyon, fonlama, long/short, taker)")
    b.add_argument("--tur2", action="store_true", help="geliştirme turu 2: göreli güç, başabaş stop, günlük tetik, "
                                                       "hayatta kalma, tek hesap portföy (DENEYLER.md §2)")

    alt.add_parser("ileri-test", help="ileri test sonucunu arşivden yeniden hesapla (DENEYLER.md §3)")

    i = alt.add_parser("indir", help="geçmiş veriyi indir (data.binance.vision)")
    i.add_argument("--semboller", nargs="*")
    i.add_argument("--ilk", type=int, default=0, help="arşiv hacim sırasına göre ilk N sembol")
    i.add_argument("--bitis", default=None)

    a = ap.parse_args(argv)
    if a.komut == "backtest":
        _log_kur("INFO", KOK / "loglar" / "backtest.log")
        from vadeli import rapor_uret

        if a.tur2:
            from vadeli import rapor_tur2

            rapor_tur2.uret()
            print((rapor_uret.D.RAPOR_DIZINI / "ozet_tur2.md").read_text())
            return 0
        if a.turev:
            from vadeli import rapor_turev

            rapor_turev.uret()
            print((rapor_uret.D.RAPOR_DIZINI / "ozet_turev.md").read_text())
            return 0
        izg = tuple(a.izgara) if a.izgara is not None else tuple(rapor_uret.varyantlar())
        rp = rapor_uret.uret(demo=a.demo, semboller=a.semboller, hizli=a.hizli, bitis=a.bitis, izgara_varyantlari=izg)
        print((rapor_uret.D.RAPOR_DIZINI / "ozet.md").read_text())
        print(f"\nRaporlar: {rapor_uret.D.RAPOR_DIZINI}  (panoda 'Backtest' sekmesi)")
        return 0
    if a.komut == "ileri-test":
        _log_kur("INFO", KOK / "loglar" / "ileri_test.log")
        from vadeli import ileri_test

        print(ileri_test.metin(ileri_test.uret()))
        return 0
    if a.komut == "indir":
        _log_kur("INFO")
        from vadeli import veri

        semboller = a.semboller or []
        if a.ilk:
            ay = a.bitis or None
            import pandas as pd
            ay = ay or str(pd.Timestamp.now(tz="UTC").to_period("M") - 1)
            semboller += [s for s, _ in veri.arsivden_hacim_sirasi(ay, a.ilk)]
        for s in semboller:
            df, f = veri.gecmis_yukle(s, "2020-01", a.bitis)
            print(f"{s}: {len(df)} mum ({df.index[0] if len(df) else '-'} → {df.index[-1] if len(df) else '-'}), {len(f)} fonlama")
        return 0
    if a.komut == "tara":
        from vadeli import ayarlar as A

        cfg = A.yukle(a.config, a)
        _log_kur(cfg.log_seviye, KOK / "loglar" / "tarayici.log")
        from vadeli.uygulama import calistir

        return calistir(cfg, demo=a.demo, demo_hiz=a.demo_hiz, pano=not a.pano_yok, terminal=not a.sessiz)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
