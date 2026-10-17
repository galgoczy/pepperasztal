<?php
/**
 * Pepper Admin - kozos betoltes.
 *
 * A konfiguracio (adatbazis, kesobb tokenek) egy PHP fajl, ami egy tombot
 * ad vissza. Soha nincs a gitben, es a deploy sem irja felul. Keresesi
 * sorrend:
 *   1. pepperadmin-config.php a webmappa FELETT, 1-4 szinttel feljebb
 *      (Hostingeren az aldomain mappaja gyakran a fodomain public_html-je
 *      alatt van, igy a "public_html folott" ket szinttel feljebb esik)
 *   2. config.php a webmappaban (a .htaccess tiltja a letoltest)
 */

declare(strict_types=1);

const PA_VERSION = '0.1.1';

/** Hol talaltuk a konfiguraciot: [utvonal, hely-leiras] vagy [null, null]. */
function pa_config_location(): array
{
    static $loc = null;
    if ($loc !== null) {
        return $loc;
    }
    $webroot = dirname(__DIR__);
    $dir = $webroot;
    for ($up = 1; $up <= 4; $up++) {
        $parent = dirname($dir);
        if ($parent === $dir) {
            break;               // elertuk a fajlrendszer gyokeret
        }
        $dir = $parent;
        // Az open_basedir a felsobb szinteken tilthatja a hozzaferest -
        // ilyenkor csendben tovabblepunk.
        $p = $dir . '/pepperadmin-config.php';
        if (@is_file($p)) {
            return $loc = [$p, "a webmappa felett {$up} szinttel"];
        }
    }
    $p = $webroot . '/config.php';
    if (is_file($p)) {
        return $loc = [$p, 'a webmappaban (config.php)'];
    }
    return $loc = [null, null];
}

function pa_config_path(): ?string
{
    return pa_config_location()[0];
}

function pa_config(): array
{
    static $cfg = null;
    if ($cfg === null) {
        $p = pa_config_path();
        $cfg = $p ? require $p : [];
        if (!is_array($cfg)) {
            $cfg = [];
        }
    }
    return $cfg;
}

function pa_db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $c = pa_config();
        $dsn = sprintf('mysql:host=%s;dbname=%s;charset=utf8mb4',
            $c['db_host'] ?? 'localhost', $c['db_name'] ?? '');
        $pdo = new PDO($dsn, $c['db_user'] ?? '', $c['db_pass'] ?? '', [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
            PDO::ATTR_TIMEOUT            => 5,
        ]);
    }
    return $pdo;
}

/** A telepites allapota - csak igen/nem jellegu adat, titok nelkul. */
function pa_status(): array
{
    $build = @file_get_contents(dirname(__DIR__) . '/build.txt');
    $st = [
        'version' => PA_VERSION,
        'build'   => $build !== false ? trim($build) : 'helyi',
        'php'     => PHP_VERSION,
        'config'  => pa_config_path() !== null,
        // Csak relativ hely ("a webmappa felett 2 szinttel"), szerverutvonal nem.
        'config_hely' => pa_config_location()[1],
        'db'      => 'nincs beallitva',
    ];
    if ($st['config']) {
        try {
            pa_db()->query('SELECT 1');
            $st['db'] = 'ok';
        } catch (Throwable $e) {
            // A hibauzenet (host, felhasznalo) nem megy ki - csak a naploba.
            error_log('pepperadmin db: ' . $e->getMessage());
            $st['db'] = 'hiba';
        }
    }
    $st['ok'] = $st['config'] && $st['db'] === 'ok';
    return $st;
}

function pa_security_headers(): void
{
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Referrer-Policy: no-referrer');
    header("Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'");
    header('X-Robots-Tag: noindex, nofollow');
}
