"""Fiyat alarmı aşamaları (mobil/analiz.js): yaklaştı → anlık geçti → kapanışla teyit / sahte kırılım."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MOBIL = Path(__file__).resolve().parents[2]  # depo kökü
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node yok")

BETIK = r"""
const depo = {}; globalThis.localStorage = { getItem: (k) => depo[k] ?? null, setItem: (k, v) => { depo[k] = String(v); } };
globalThis.sessionStorage = globalThis.localStorage;
const olaylar = []; globalThis.document = { dispatchEvent: (e) => { if (e.detail) olaylar.push(e.detail); } };
globalThis.window = {};
let simdi = 1.8e12; Date.now = () => simdi;
let fiyat = 3.0, mumKapanis = 2.9, kapanisZamani = simdi - 3600e3;
globalThis.fetch = async (u) => {
  const url = new URL(u);
  let body;
  if (url.pathname === '/api/v3/ticker/price') body = [{ symbol: 'XUSDT', price: String(fiyat) }];
  else if (url.pathname === '/api/v3/klines') body = [[kapanisZamani - 4 * 3600e3, '1', '1', '1', String(mumKapanis), '1', kapanisZamani - 1, '1']];
  return { ok: true, status: 200, json: async () => body, headers: { get: () => null } };
};
const A = await import('./analiz.js');
A.alarmEkle({ sembol: 'XUSDT', seviye: 4.0, yon: 'yukari', tf: '4h' });
const durum = () => A.alarmlar()[0].durum;
const sonuc = [];
await A.alarmKontrol(); sonuc.push(durum());                // 3.00: bekliyor
fiyat = 3.97; await A.alarmKontrol(); sonuc.push(durum());   // %1 içinde: yaklaştı
fiyat = 4.05; mumKapanis = 4.2;                               // geçti; son kapanan mum kırılımdan ÖNCE (üstünde bile olsa sayılmaz)
await A.alarmKontrol(); sonuc.push(durum());                // gecti
simdi += 4 * 3600e3; kapanisZamani = simdi - 60e3; mumKapanis = 3.95;  // kırılımdan sonra kapanan mum geri kapandı
await A.alarmKontrol(); sonuc.push(durum());                // sahte kırılım → bekliyor
fiyat = 4.10; await A.alarmKontrol(); sonuc.push(durum());   // yeniden geçti
simdi += 4 * 3600e3; kapanisZamani = simdi - 60e3; mumKapanis = 4.12;
await A.alarmKontrol(); sonuc.push(durum());                // teyit
console.log(JSON.stringify({ sonuc, olaylar }));
"""


def test_alarm_asamalari(tmp_path):
    for ad in ("analiz.js", "tarama.js", "formasyon.js", "strateji.js", "meta.js"):
        (tmp_path / ad).write_text((MOBIL / ad).read_text())
    (tmp_path / "t.mjs").write_text(BETIK)
    out = json.loads(subprocess.run(["node", str(tmp_path / "t.mjs")], capture_output=True, text=True, check=True).stdout)
    assert out["sonuc"] == ["bekliyor", "yaklasti", "gecti", "bekliyor", "gecti", "teyit"], out
    assert any("TEYİT" in x for x in out["olaylar"]) and any("sahte" in x for x in out["olaylar"])
