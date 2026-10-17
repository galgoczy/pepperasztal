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
