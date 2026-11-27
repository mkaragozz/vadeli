"""SQLite: sinyaller, pozisyonlar, mum önbelleği, ayarlar, bildirim tekrar önleme, web push abonelikleri."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd

SEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sinyaller (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  zaman TEXT NOT NULL,            -- sinyal mumunun açılış zamanı (UTC ISO)
  sembol TEXT NOT NULL, yon TEXT NOT NULL, yeni INTEGER NOT NULL,
  fiyat REAL NOT NULL, stop REAL NOT NULL, atr REAL, kaldirac REAL, notional REAL, teminat REAL,
  likidasyon REAL, risk_usdt REAL, rejim INTEGER, hacim24 REAL, param_surum TEXT,
  olusturma REAL NOT NULL,
  durum TEXT DEFAULT 'bekliyor',  -- bekliyor | acik | kapali
  giris REAL, cikis_zaman TEXT, cikis_fiyat REAL, r REAL, sure_saat REAL, cikis_neden TEXT,
  UNIQUE(sembol, yon, zaman)
);
CREATE INDEX IF NOT EXISTS ix_sinyal_zaman ON sinyaller(zaman);
CREATE TABLE IF NOT EXISTS pozisyonlar (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sembol TEXT NOT NULL, yon TEXT NOT NULL, giris REAL NOT NULL, adet REAL NOT NULL, kaldirac REAL NOT NULL,
  stop REAL NOT NULL, ilk_stop REAL, acilis TEXT NOT NULL, sinyal_id INTEGER, not_metni TEXT DEFAULT '',
  durum TEXT DEFAULT 'acik', kapanis TEXT, kapanis_fiyat REAL,
  -- son değerlendirme (her 1s kapanışında güncellenir)
  son_fiyat REAL, pnl REAL, r REAL, onerilen_stop REAL, cikis_sinyali INTEGER DEFAULT 0,
  stop_yakin INTEGER DEFAULT 0, liq_yakin INTEGER DEFAULT 0, likidasyon REAL, degerlendirme TEXT
);
CREATE TABLE IF NOT EXISTS mumlar (
  sembol TEXT NOT NULL, aralik TEXT NOT NULL, t INTEGER NOT NULL,
  o REAL, h REAL, l REAL, c REAL, v REAL, qv REAL,
  PRIMARY KEY (sembol, aralik, t)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bildirimler (anahtar TEXT PRIMARY KEY, zaman REAL NOT NULL);
CREATE TABLE IF NOT EXISTS push_abonelik (endpoint TEXT PRIMARY KEY, veri TEXT NOT NULL, zaman REAL NOT NULL);
"""


class DB:
    def __init__(self, yol: str | Path):
        self.yol = str(yol)
        if self.yol != ":memory:":
            Path(self.yol).parent.mkdir(parents=True, exist_ok=True)
        self._kilit = threading.RLock()
        self.c = sqlite3.connect(self.yol, check_same_thread=False, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SEMA)

    def _yurut(self, sql: str, p: tuple | dict = ()) -> sqlite3.Cursor:
        with self._kilit:
            return self.c.execute(sql, p)

    def satirlar(self, sql: str, p: tuple | dict = ()) -> list[dict]:
        with self._kilit:
            return [dict(r) for r in self.c.execute(sql, p).fetchall()]

    # ---- ayarlar
    def ayarlar_oku(self) -> dict[str, Any]:
        return {r["anahtar"]: json.loads(r["deger"]) for r in self.satirlar("SELECT * FROM ayarlar")}

    def ayar_yaz(self, d: dict[str, Any]) -> None:
        with self._kilit:
            for k, v in d.items():
                self.c.execute("INSERT INTO ayarlar(anahtar, deger) VALUES(?, ?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger",
                               (k, json.dumps(v)))

    # ---- bildirim tekrarı
    def bildirim_ilk_mi(self, anahtar: str) -> bool:
        """Aynı anahtar için yalnızca ilk çağrı True döner (sembol+yön+mum başına bir bildirim)."""
        with self._kilit:
            cur = self.c.execute("INSERT OR IGNORE INTO bildirimler(anahtar, zaman) VALUES(?, ?)", (anahtar, time.time()))
            return cur.rowcount == 1

    # ---- sinyaller
    def sinyal_ekle(self, s: dict) -> int | None:
        alanlar = ["zaman", "sembol", "yon", "yeni", "fiyat", "stop", "atr", "kaldirac", "notional", "teminat",
                   "likidasyon", "risk_usdt", "rejim", "hacim24", "param_surum"]
        vals = [s.get(a) for a in alanlar]
        vals[3] = int(bool(vals[3]))
        with self._kilit:
            cur = self.c.execute(f"INSERT OR IGNORE INTO sinyaller({','.join(alanlar)}, olusturma) VALUES({','.join('?' * len(alanlar))}, ?)",
                                 (*vals, time.time()))
            return cur.lastrowid if cur.rowcount == 1 else None

    def sinyal_sonuc_yaz(self, sid: int, d: dict) -> None:
        self._yurut("UPDATE sinyaller SET durum=?, giris=?, cikis_zaman=?, cikis_fiyat=?, r=?, sure_saat=?, cikis_neden=? WHERE id=?",
                    (d.get("durum"), d.get("giris"), d.get("cikis_zaman"), d.get("cikis_fiyat"), d.get("r"),
                     d.get("sure_saat"), d.get("neden"), sid))

    def sinyaller(self, limit: int = 500, acik_degil: bool = False) -> list[dict]:
        q = "SELECT * FROM sinyaller"
        if acik_degil:
            q += " WHERE durum != 'kapali'"
        return self.satirlar(q + " ORDER BY zaman DESC, id DESC LIMIT ?", (limit,))

    # ---- pozisyonlar
    def pozisyon_ekle(self, p: dict) -> int:
        cur = self._yurut("INSERT INTO pozisyonlar(sembol, yon, giris, adet, kaldirac, stop, ilk_stop, acilis, sinyal_id, not_metni) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (p["sembol"], p["yon"], p["giris"], p["adet"], p["kaldirac"], p["stop"], p["stop"], p["acilis"],
                           p.get("sinyal_id"), p.get("not_metni", "")))
        return int(cur.lastrowid)

    def pozisyonlar(self, acik: bool | None = None) -> list[dict]:
        if acik is None:
            return self.satirlar("SELECT * FROM pozisyonlar ORDER BY durum='acik' DESC, id DESC")
        return self.satirlar("SELECT * FROM pozisyonlar WHERE durum=? ORDER BY id DESC", ("acik" if acik else "kapali",))

    def pozisyon(self, pid: int) -> dict | None:
        r = self.satirlar("SELECT * FROM pozisyonlar WHERE id=?", (pid,))
        return r[0] if r else None

    def pozisyon_guncelle(self, pid: int, d: dict) -> None:
        izinli = {"stop", "not_metni", "durum", "kapanis", "kapanis_fiyat", "son_fiyat", "pnl", "r", "onerilen_stop",
                  "cikis_sinyali", "stop_yakin", "liq_yakin", "likidasyon", "degerlendirme"}
        d = {k: v for k, v in d.items() if k in izinli}
        if not d:
            return
        self._yurut(f"UPDATE pozisyonlar SET {', '.join(f'{k}=?' for k in d)} WHERE id=?", (*d.values(), pid))

    def pozisyon_sil(self, pid: int) -> None:
        self._yurut("DELETE FROM pozisyonlar WHERE id=?", (pid,))

    # ---- mum önbelleği
    def mum_yaz(self, sembol: str, aralik: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        t = (df.index.as_unit("ms").asi8).tolist()
        satir = list(zip([sembol] * len(df), [aralik] * len(df), t, df["open"], df["high"], df["low"], df["close"],
                         df["volume"], df["quote_volume"]))
        with self._kilit:
            self.c.execute("BEGIN")
            self.c.executemany("INSERT OR REPLACE INTO mumlar VALUES(?,?,?,?,?,?,?,?,?)", satir)
            self.c.execute("COMMIT")

    def mum_oku(self, sembol: str, aralik: str = "1h", son: int = 5000) -> pd.DataFrame:
        from .veri import satirlardan_df

        r = self.satirlar("SELECT t,o,h,l,c,v,qv FROM (SELECT * FROM mumlar WHERE sembol=? AND aralik=? ORDER BY t DESC LIMIT ?) ORDER BY t",
                          (sembol, aralik, son))
        return satirlardan_df([[x["t"], x["o"], x["h"], x["l"], x["c"], x["v"], x["qv"]] for x in r])

    def mum_buda(self, sembol: str, aralik: str, tut: int) -> None:
        self._yurut("DELETE FROM mumlar WHERE sembol=? AND aralik=? AND t < (SELECT MIN(t) FROM (SELECT t FROM mumlar "
                    "WHERE sembol=? AND aralik=? ORDER BY t DESC LIMIT ?))", (sembol, aralik, sembol, aralik, tut))

    # ---- push
    def push_ekle(self, abonelik: dict) -> None:
        self._yurut("INSERT OR REPLACE INTO push_abonelik VALUES(?,?,?)", (abonelik["endpoint"], json.dumps(abonelik), time.time()))

    def push_liste(self) -> list[dict]:
        return [json.loads(r["veri"]) for r in self.satirlar("SELECT veri FROM push_abonelik")]

    def push_sil(self, endpoint: str) -> None:
        self._yurut("DELETE FROM push_abonelik WHERE endpoint=?", (endpoint,))
