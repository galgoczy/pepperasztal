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
    <a href="/jelszo.php">Jelszó-hash</a>
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
