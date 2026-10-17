<?php
/**
 * Pepper Admin - nyitooldal. Egyelore csak a telepites allapotat mutatja;
 * adat (gepek, mentesek) a kovetkezo lepesben, belepes moge.
 */

declare(strict_types=1);
require __DIR__ . '/lib/bootstrap.php';

pa_security_headers();
header('Cache-Control: no-store');
$st = pa_status();

// A health.php gepi (ekezet nelkuli) allapotai magyarul az oldalon.
const DB_LABEL = [
    'ok'              => 'működik',
    'hiba'            => 'nem érhető el',
    'nincs beallitva' => 'nincs beállítva',
];

function row(string $label, string $value, bool $good): string
{
    return sprintf('<tr><th>%s</th><td class="%s">%s</td></tr>',
        htmlspecialchars($label), $good ? 'ok' : 'bad', htmlspecialchars($value));
}
?><!doctype html>
<html lang="hu">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Pepper Admin</title>
<style>
  :root { --red: #E52721; --ink: #141414; --bg: #F8F7F5; --muted: #6b6b6b;
          --ok: #1f7a3a; --bad: #b3261e; --card: #fff; --line: #e7e4df; }
  @media (prefers-color-scheme: dark) {
    :root { --ink: #f2f0ec; --bg: #141414; --card: #1d1d1d; --line: #2c2c2c;
            --muted: #a3a3a3; --ok: #5fd08a; --bad: #ff8a80; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         background: var(--bg); color: var(--ink); }
  main { max-width: 560px; margin: 0 auto; padding: 48px 16px; }
  h1 { font-size: 28px; margin: 0 0 4px; }
  h1 span { color: var(--red); }
  p { color: var(--muted); margin: 0 0 24px; }
  table { width: 100%; border-collapse: collapse; background: var(--card);
          border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
  th, td { text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--line); }
  tr:last-child th, tr:last-child td { border-bottom: 0; }
  th { font-weight: 500; color: var(--muted); width: 45%; }
  td { font-weight: 600; font-variant-numeric: tabular-nums; }
  .ok { color: var(--ok); } .bad { color: var(--bad); }
</style>
</head>
<body>
<main>
  <h1><span>Pepper</span> Admin</h1>
  <p>Telepítési állapot. A gépek és a mentések itt jelennek majd meg.</p>
  <table>
    <?= row('Verzió', $st['version'], true) ?>
    <?= row('Build (commit)', $st['build'], true) ?>
    <?= row('PHP', $st['php'], version_compare($st['php'], '7.4', '>=')) ?>
    <?= row('Konfiguráció', $st['config'] ? 'megvan – ' . $st['config_hely'] : 'hiányzik', $st['config']) ?>
    <?= row('Adatbázis', DB_LABEL[$st['db']] ?? $st['db'], $st['db'] === 'ok') ?>
  </table>
</main>
</body>
</html>
