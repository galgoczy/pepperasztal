<?php
/**
 * POST /api/jelentes.php - a POS gepek percenkenti eletjele.
 *
 * Fejlec:  X-Pepper-Token: <helyszin tokenje>
 * Torzs:   JSON { helyszin, gep, agent_verzio, ..., kartyak } (max 1 MB)
 *
 * A token a szerveren csak sha256-hash-kent van meg. A torzsben kuldott
 * helyszin-kulcsnak egyeznie kell a tokenhez tartozoval - igy egy rossz
 * gepre masolt ini nem irja felul egy masik helyszin allapotat.
 *
 * Valasz: { ok, szerver_ido, frissites: null | { verzio, sha256 },
 *           naplo_ig?, pillanatkep_ok?, egyeztetes_ok? }
 * A kartyak resze (feltoltos kartyak mozgasai): lib/kartyak.php.
 * A frissitest a gep csak akkor kapja meg, ha az adminban erre a
 * helyszinre ki lett jelolve (cel_verzio), es van ilyen alairt kiadas.
 * PARANCSOT a felho nem kuld - a kommunikacio egyiranyu.
 */

declare(strict_types=1);
require __DIR__ . '/../lib/bootstrap.php';
require __DIR__ . '/../lib/schema.php';
require __DIR__ . '/../lib/kiadas.php';
require __DIR__ . '/../lib/kartyak.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function fail(int $code, string $msg): void
{
    http_response_code($code);
    echo json_encode(['ok' => false, 'hiba' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    fail(405, 'csak POST');
}
$token = (string)($_SERVER['HTTP_X_PEPPER_TOKEN'] ?? '');
if (!preg_match('/^[a-f0-9]{64}$/', $token)) {
    fail(401, 'hianyzo vagy hibas token');
}
$raw = file_get_contents('php://input', false, null, 0, 1048577);
if ($raw === false || strlen($raw) > 1048576) {
    fail(413, 'tul nagy torzs');
}
$in = json_decode($raw, true);
if (!is_array($in)) {
    fail(400, 'nem JSON');
}

try {
    pa_migrate();
    $db = pa_db();
    $st = $db->prepare('SELECT * FROM helyszin WHERE token_hash = ?');
    $st->execute([hash('sha256', $token)]);
    $site = $st->fetch();
    if (!$site) {
        usleep(300000);
        fail(401, 'ismeretlen token');
    }
    if ((string)($in['helyszin'] ?? '') !== $site['kulcs']) {
        fail(403, 'a token nem ehhez a helyszinhez tartozik');
    }

    $valasz = [];
    $kinfo = null;
    if (isset($in['kartyak']) && is_array($in['kartyak'])) {
        try {
            $valasz = pa_kartyak_fogad((int)$site['id'], $in['kartyak']);
        } catch (InvalidArgumentException $e) {
            // Hibas kartya-resz: az eletjel megmarad, a gep nem lep tovabb.
            $valasz = ['kartyak_hiba' => $e->getMessage()];
        }
        // A nyers jelentesbe csak az osszegzes kerul, a mozgasok nem.
        $k = $in['kartyak'];
        $kinfo = ['kurzor' => $k['kurzor'] ?? null, 'gen' => $k['gen'] ?? null,
                  'naplo_sor' => isset($k['naplo']['sorok']) ? count((array)$k['naplo']['sorok']) : 0,
                  'pillanatkep' => isset($k['pillanatkep']), 'egyeztetes' => isset($k['egyeztetes']),
                  'hiba' => $k['hiba'] ?? ($valasz['kartyak_hiba'] ?? null)];
        $in['kartyak'] = $kinfo;
    }

    $ver = substr((string)($in['agent_verzio'] ?? ''), 0, 32);
    $adat = $kinfo === null ? $raw : json_encode($in, JSON_UNESCAPED_UNICODE);
    $row = [pa_now(), pa_client_ip_api(), substr((string)($in['gep'] ?? ''), 0, 100),
            $ver, $adat, (int)$site['id']];
    $upd = $db->prepare('UPDATE jelentes SET ido = ?, ip = ?, gep = ?, agent_verzio = ?, adat = ?
                         WHERE helyszin_id = ?');
    $upd->execute($row);
    if ($upd->rowCount() === 0) {
        $db->prepare('INSERT INTO jelentes (ido, ip, gep, agent_verzio, adat, helyszin_id)
                      VALUES (?, ?, ?, ?, ?, ?)')->execute($row);
    }

    $frissites = null;
    $cel = $site['cel_verzio'];
    if ($cel && $ver !== '' && pa_ver_cmp($cel, $ver) > 0) {
        $k = pa_kiadas($cel);
        if ($k) {
            $frissites = ['verzio' => $k['verzio'], 'sha256' => $k['sha256']];
        }
    }
    echo json_encode(['ok' => true, 'szerver_ido' => pa_now(), 'frissites' => $frissites] + $valasz,
        JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    error_log('pepperadmin jelentes: ' . $e->getMessage());
    fail(500, 'szerverhiba');
}

function pa_client_ip_api(): string
{
    return substr((string)($_SERVER['REMOTE_ADDR'] ?? ''), 0, 45);
}
