<?php
/**
 * GET /api/frissites.php?verzio=X&mit=manifest|csomag
 * Fejlec: X-Pepper-Token
 *
 * Csak azt a verziot adja ki, amit az adminban erre a helyszinre
 * kijeloltek. A gep a csomagot a sajat, helyben tarolt publikus kulcsaval
 * ellenorzi - a szerver feltorese sem eleg egy hamis csomaghoz.
 */

declare(strict_types=1);
require __DIR__ . '/../lib/bootstrap.php';
require __DIR__ . '/../lib/schema.php';
require __DIR__ . '/../lib/kiadas.php';

header('Cache-Control: no-store');

function fail(int $code, string $msg): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['ok' => false, 'hiba' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

$token = (string)($_SERVER['HTTP_X_PEPPER_TOKEN'] ?? '');
if (!preg_match('/^[a-f0-9]{64}$/', $token)) {
    fail(401, 'hianyzo vagy hibas token');
}
$verzio = (string)($_GET['verzio'] ?? '');
$mit = (string)($_GET['mit'] ?? 'manifest');
if (!preg_match('/^[0-9][0-9.\-]{0,31}$/', $verzio)) {
    fail(400, 'hibas verzio');
}

try {
    pa_migrate();
    $st = pa_db()->prepare('SELECT * FROM helyszin WHERE token_hash = ?');
    $st->execute([hash('sha256', $token)]);
    $site = $st->fetch();
    if (!$site) {
        usleep(300000);
        fail(401, 'ismeretlen token');
    }
    if ($site['cel_verzio'] !== $verzio) {
        fail(403, 'ez a verzio nincs kijelolve erre a helyszinre');
    }
    $k = pa_kiadas($verzio);
    if (!$k) {
        fail(404, 'nincs ilyen alairt kiadas');
    }
    if ($mit === 'csomag') {
        header('Content-Type: application/zip');
        header('Content-Length: ' . filesize($k['zip']));
        readfile($k['zip']);
        exit;
    }
    header('Content-Type: application/json; charset=utf-8');
    unset($k['zip']);
    echo json_encode($k, JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    error_log('pepperadmin frissites: ' . $e->getMessage());
    fail(500, 'szerverhiba');
}
