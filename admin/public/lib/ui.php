<?php
/** Kozos HTML-keret es kiirasi segedek. */

declare(strict_types=1);

function h(?string $s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

/** Mennyi ideje: "most", "3 perce", "2 oraja", "4 napja". */
function pa_ago(?string $ts): string
{
    if (!$ts) {
        return 'soha';
    }
    $d = time() - strtotime($ts);
    if ($d < 60) return 'most';
    if ($d < 3600) return intdiv($d, 60) . ' perce';
    if ($d < 86400) return intdiv($d, 3600) . ' órája';
    return intdiv($d, 86400) . ' napja';
}

/** ok / warn / bad allapot egy idobelyeg korabol. */
function pa_age_class(?string $ts, int $okSec, int $warnSec): string
{
    if (!$ts) return 'bad';
    $d = time() - strtotime($ts);
    return $d <= $okSec ? 'ok' : ($d <= $warnSec ? 'warn' : 'bad');
}

function pa_page_start(string $title, ?string $user, int $refresh = 0): void
{
    pa_security_headers();
    header('Cache-Control: no-store');
    ?><!doctype html>
<html lang="hu">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title><?= h($title) ?> · Pepper Admin</title>
<meta name="csrf" content="<?= pa_csrf() ?>">
<link rel="stylesheet" href="/style.css">
<script src="/app.js" defer></script>
</head>
<body<?= $refresh > 0 ? ' data-refresh="' . $refresh . '"' : '' ?>>
<header class="top">
  <a class="brand" href="/"><span>Pepper</span> Admin</a>
<?php if ($user): ?>
  <nav>
    <a href="/">Helyszínek</a>
    <a href="/naplo.php">Napló</a>
    <a href="/passkey.php">Passkeyek</a>
    <a href="/vonalkod.php">Vonalkód</a>
    <form method="post" action="/kilepes.php"><?= pa_csrf_field() ?><button class="link"><?= h($user) ?> · Kilépés</button></form>
  </nav>
<?php endif; ?>
</header>
<main>
<?php
}

function pa_page_end(): void
{
    echo "</main>\n</body>\n</html>\n";
}

/** A jelentes JSON-jat biztonsagosan dekodolja (hibanal ures tomb). */
function pa_json(?string $s): array
{
    $d = json_decode((string)$s, true);
    return is_array($d) ? $d : [];
}

/**
 * A gep terhelese a jelentesbol, egysegesen. Az ugynok CPU-ja az egesz gep
 * (minden mag) egy percere vetitve: CPU-masodperc / (60 * magok szama).
 * A 2026-10-19.5-os ugynok a "gep" kulcson kuldte, es a gep CPU-jat csak a
 * sajat futasa alatt merte (ezt "futas alatt" jeloli).
 */
function pa_terheles(array $a): array
{
    $g = $a['terheles'] ?? (is_array($a['gep'] ?? null) ? $a['gep'] : null);
    if (!is_array($g) || isset($g['hiba'])) {
        return is_array($g) ? ['hiba' => (string)$g['hiba']] : [];
    }
    $mag = max(1, (int)($g['cpu_db'] ?? 1));
    $ki = $g + ['mag' => $mag, 'perc_ablak' => isset($g['cpu_ablak_mp'])];
    if (isset($g['sajat_cpu_mp'])) {
        $ki['ugynok_perc'] = round(100.0 * (float)$g['sajat_cpu_mp'] / (60.0 * $mag), 2);
    }
    return $ki;
}
