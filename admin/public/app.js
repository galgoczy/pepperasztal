// Pepper Admin - a CSP (default-src 'self') miatt nincs beagyazott script.
// <form data-confirm="..."> : megerosites bekuldes elott
// <body data-refresh="30">  : automatikus ujratoltes, ha nem gepel senki
document.addEventListener('submit', function (e) {
  var msg = e.target.getAttribute('data-confirm');
  if (msg && !window.confirm(msg)) { e.preventDefault(); }
});
(function () {
  var s = parseInt(document.body.getAttribute('data-refresh') || '0', 10);
  if (s > 0) {
    setTimeout(function () {
      var a = document.activeElement;
      if (!a || (a.tagName !== 'INPUT' && a.tagName !== 'SELECT')) { location.reload(); }
    }, s * 1000);
  }
})();

// ---- passkey -----------------------------------------------------------
// <button data-passkey-login>      belepes passkey-jel
// <form data-passkey-reg>          uj passkey (name="nev" mezo)
// <div data-passkey-msg hidden>    hibauzenet helye
(function () {
  var meta = document.querySelector('meta[name="csrf"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var msgEl = document.querySelector('[data-passkey-msg]');

  function msg(t) {
    if (!msgEl) { if (t) { window.alert(t); } return; }
    msgEl.textContent = t || '';
    msgEl.hidden = !t;
  }
  function b64u(buf) {
    var s = '', b = new Uint8Array(buf);
    for (var i = 0; i < b.length; i++) { s += String.fromCharCode(b[i]); }
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function unb64u(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) { s += '='; }
    var bin = atob(s), b = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { b[i] = bin.charCodeAt(i); }
    return b.buffer;
  }
  function post(mit, body) {
    return fetch('/api/passkey.php?mit=' + mit, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, hiba: 'Szerverhiba (' + r.status + ').' }; });
    }).then(function (d) {
      if (!d.ok) { throw new Error(d.hiba || 'Hiba.'); }
      return d;
    });
  }
  function emberi(e) {
    if (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) {
      return 'Megszakítva vagy lejárt. Próbáld újra.';
    }
    if (e && e.name === 'InvalidStateError') {
      return 'Ezen az eszközön már van passkey-d ehhez a fiókhoz.';
    }
    return (e && e.message) || 'Hiba.';
  }
  function tamogatott() {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      msg('Ez a böngésző nem támogatja a passkey-t.');
      return false;
    }
    return true;
  }

  var be = document.querySelector('[data-passkey-login]');
  if (be) {
    be.addEventListener('click', function (e) {
      e.preventDefault();
      if (!tamogatott()) { return; }
      msg('');
      be.disabled = true;
      post('be_opciok').then(function (d) {
        var o = d.opciok;
        o.challenge = unb64u(o.challenge);
        return navigator.credentials.get({ publicKey: o });
      }).then(function (c) {
        var r = c.response;
        return post('be_kesz', { cred: {
          rawId: b64u(c.rawId),
          clientDataJSON: b64u(r.clientDataJSON),
          authenticatorData: b64u(r.authenticatorData),
          signature: b64u(r.signature),
          userHandle: r.userHandle ? b64u(r.userHandle) : ''
        } });
      }).then(function () {
        location.href = '/';
      }).catch(function (err) {
        msg(emberi(err));
        be.disabled = false;
      });
    });
  }

  var reg = document.querySelector('form[data-passkey-reg]');
  if (reg) {
    reg.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!tamogatott()) { return; }
      msg('');
      var gomb = reg.querySelector('button');
      var nev = (reg.querySelector('[name="nev"]') || {}).value || '';
      gomb.disabled = true;
      post('reg_opciok').then(function (d) {
        var o = d.opciok;
        o.challenge = unb64u(o.challenge);
        o.user.id = unb64u(o.user.id);
        o.excludeCredentials = (o.excludeCredentials || []).map(function (x) {
          return { type: x.type, id: unb64u(x.id) };
        });
        return navigator.credentials.create({ publicKey: o });
      }).then(function (c) {
        return post('reg_kesz', { nev: nev, cred: {
          rawId: b64u(c.rawId),
          clientDataJSON: b64u(c.response.clientDataJSON),
          attestationObject: b64u(c.response.attestationObject)
        } });
      }).then(function () {
        location.href = location.pathname === '/passkey.php' ? '/passkey.php' : '/';
      }).catch(function (err) {
        msg(emberi(err));
        gomb.disabled = false;
      });
    });
  }
})();
