/* Tema seçimi (telefon ve pano ortak). <head> içinde, CSS'ten hemen sonra yüklenir: sayfa yanlış renkte yanıp sönmez.
 * Seçenekler: otomatik (cihaz ayarı) · açık · koyu · karma (koyu üst/alt çubuk + açık içerik). Seçim yalnız bu cihazda saklanır. */
(function () {
  var SIRA = ["otomatik", "acik", "koyu", "karma"];
  var AD = { otomatik: "Otomatik", acik: "Açık", koyu: "Koyu", karma: "Karma" };
  var IKON = { otomatik: "◐", acik: "☀", koyu: "☾", karma: "◑" };
  function oku() { try { var t = localStorage.getItem("tema"); return SIRA.indexOf(t) >= 0 ? t : "otomatik"; } catch (e) { return "otomatik"; } }
  function uygula(t) {
    var kok = document.documentElement;
    if (t === "otomatik") kok.removeAttribute("data-tema"); else kok.setAttribute("data-tema", t);
    var koyuMu = t === "koyu" || t === "karma" || (t === "otomatik" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", koyuMu ? "#0b0e11" : "#ffffff");
    var d = document.getElementById("temaDugme");
    if (d) { d.textContent = IKON[t]; d.title = "Tema: " + AD[t] + " (değiştirmek için dokun)"; d.setAttribute("aria-label", d.title); }
  }
  uygula(oku());
  document.addEventListener("DOMContentLoaded", function () {
    uygula(oku());
    var d = document.getElementById("temaDugme");
    if (d) d.addEventListener("click", function () {
      var t = SIRA[(SIRA.indexOf(oku()) + 1) % SIRA.length];
      try { localStorage.setItem("tema", t); } catch (e) { /* özel mod */ }
      uygula(t);
      var b = document.getElementById("bildirim");
      if (b) { b.textContent = "Tema: " + AD[t]; b.classList.remove("gizli"); clearTimeout(b._t); b._t = setTimeout(function () { b.classList.add("gizli"); }, 1800); }
    });
  });
})();
