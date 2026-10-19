/*
 * Vonalkod-teszt: Code 128 (B keszlet) SVG-ben, telefon kijelzojere.
 * A kod csak a bongeszoben el, a szerverre nem megy fel.
 */
(function () {
  'use strict';

  // Code 128 szelessegek (savszelesseg, kozszelesseg felvaltva), 0..106.
  var MINTA = ('212222,222122,222221,121223,121322,131222,122213,122312,132212,221213,' +
    '221312,231212,112232,122132,122231,113222,123122,123221,223211,221132,221231,213212,' +
    '223112,312131,311222,321122,321221,312212,322112,322211,212123,212321,232121,111323,' +
    '131123,131321,112313,132113,132311,211313,231113,231311,112133,112331,132131,113123,' +
    '113321,133121,313121,211331,231131,213113,213311,213131,311123,311321,331121,312113,' +
    '312311,332111,314111,221411,431111,111224,111422,121124,121421,141122,141221,112214,' +
    '112412,122114,122411,142112,142211,241211,221114,413111,241112,134111,111242,121142,' +
    '121241,114212,124112,124211,411212,421112,421211,212141,214121,412121,111143,111341,' +
    '131141,114113,114311,411113,411311,113141,114131,311141,411131,211412,211214,211232,' +
    '2331112').split(',');
  var START_B = 104, STOP = 106;

  /** A jelek ertekei (start, adat, ellenorzo, stop) vagy null, ha nem kodolhato. */
  function ertekek(s) {
    var v = [START_B], osszeg = START_B;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 32 || c > 126) return null;
      v.push(c - 32);
      osszeg += (c - 32) * (i + 1);
    }
    v.push(osszeg % 103, STOP);
    return v;
  }

  function svg(s) {
    var v = ertekek(s);
    if (!v) return null;
    var csend = 12, x = csend, savok = '';
    v.forEach(function (e) {
      var w = MINTA[e];
      for (var j = 0; j < w.length; j++) {
        var sz = +w[j];
        if (j % 2 === 0) savok += '<rect x="' + x + '" y="0" width="' + sz + '" height="60"/>';
        x += sz;
      }
    });
    var szel = x + csend;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + szel + ' 60" ' +
      'preserveAspectRatio="none" shape-rendering="crispEdges">' +
      '<rect width="' + szel + '" height="60" fill="#fff"/><g fill="#000">' + savok + '</g></svg>';
  }

  var be = document.getElementById('kod');
  var hely = document.getElementById('kodok');
  if (!be || !hely) return;

  function valtozatok(s) {
    var ki = [{ cim: 'Pontosan így', kod: s }];
    var szamok = s.replace(/[^0-9]/g, '');
    if (szamok && szamok !== s) ki.push({ cim: 'Csak a számjegyek', kod: szamok });
    if (szamok && s !== ';' + szamok + '?') ki.push({ cim: 'Elválasztókkal', kod: ';' + szamok + '?' });
    return ki;
  }

  function rajzol() {
    var s = be.value.trim();
    try { localStorage.setItem('vonalkod', s); } catch (e) {}
    hely.textContent = '';
    if (!s) return;
    valtozatok(s).forEach(function (t) {
      var k = svg(t.kod);
      var d = document.createElement('div');
      d.className = 'vk';
      var c = document.createElement('p');
      c.className = 'vk-cim';
      c.textContent = t.cim + ': ' + t.kod;
      d.appendChild(c);
      var b = document.createElement('div');
      b.className = 'vk-kep';
      if (k) b.innerHTML = k; else b.textContent = 'Ez a kód nem kódolható (csak ASCII-karakterek).';
      d.appendChild(b);
      hely.appendChild(d);
    });
  }

  try { be.value = localStorage.getItem('vonalkod') || ''; } catch (e) {}
  be.addEventListener('input', rajzol);
  rajzol();

  // A kepernyo ne aludjon el, amig az oldal latszik (ahol a bongeszo tamogatja).
  var zar = null;
  function ebren() {
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    navigator.wakeLock.request('screen').then(function (z) { zar = z; }).catch(function () {});
  }
  document.addEventListener('visibilitychange', ebren);
  ebren();
})();
