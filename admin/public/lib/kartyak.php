<?php
/**
 * Feltoltos kartyak: a gepek jelentesenek "kartyak" resze (agent/kartyak.py).
 *
 *   naplo:       { tol, ig, sorok: [{id, kartya, tipus, osszeg, elotte, ido}] }
 *   pillanatkep: { ido, gen, nevek, lista: [{id, egyenleg, ervenyes, nev?}] }
 *                (a nev titkositva kerul az adatbazisba; nevek = false eseten
 *                a helyszin minden tarolt nevet toroljuk)
 *   egyeztetes:  { ido, kartyak, naplo_nelkul, elteres: [...] }
 *
 * A mozgasok (helyszin, naplo-ID) szerint egyediek: az ujrakuldott sorok
 * nem duplazodnak. A valasz visszaigazolja, mit mentettunk - a gep csak
 * ennek alapjan lep tovabb.
 */

declare(strict_types=1);

require_once __DIR__ . '/titok.php';

const PA_KTIPUS = ['FK' => 'Költés', 'KF' => 'Feltöltés', 'HF' => 'Hitel fel', 'FH' => 'Hitel vissza'];

function pa_penz($v): ?string
{
    if ($v === null || $v === '') {
        return null;
    }
    if (!is_string($v) && !is_int($v) && !is_float($v)) {
        throw new InvalidArgumentException('rossz osszeg');
    }
    if (!preg_match('/^-?\d{1,12}(\.\d{1,2})?$/', (string)$v)) {
        throw new InvalidArgumentException('rossz osszeg');
    }
    return number_format((float)$v, 2, '.', '');
}

function pa_ido_ok($v): ?string
{
    $v = (string)$v;
    return preg_match('/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/', $v) ? $v : null;
}

function pa_beszur_ignore(): string
{
    return pa_is_sqlite() ? 'INSERT OR IGNORE' : 'INSERT IGNORE';
}

/** Feldolgozza a jelentes kartya-reszet; a valaszba kerulo mezoket adja. */
function pa_kartyak_fogad(int $hid, array $k): array
{
    $db = pa_db();
    $ki = [];
    $info = ['kurzor' => (int)($k['kurzor'] ?? 0), 'gen' => isset($k['gen']) ? (int)$k['gen'] : null];
    if (isset($k['hiba'])) {
        $info['hiba'] = mb_substr((string)$k['hiba'], 0, 200);
    }

    if (isset($k['naplo']) && is_array($k['naplo'])) {
        $n = $k['naplo'];
        $tol = (int)($n['tol'] ?? -1);
        $ig = (int)($n['ig'] ?? -1);
        $sorok = $n['sorok'] ?? null;
        if ($tol < 0 || $ig < $tol || !is_array($sorok) || count($sorok) > 1000) {
            throw new InvalidArgumentException('hibas naplo-resz');
        }
        $db->beginTransaction();
        try {
            $ins = $db->prepare(pa_beszur_ignore() . ' INTO kartyamozgas
                (helyszin_id, naplo_id, kartya_id, tipus, osszeg, elotte, ido, erkezett)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
            $uj = 0;
            foreach ($sorok as $r) {
                $id = (int)($r['id'] ?? 0);
                $kid = (int)($r['kartya'] ?? 0);
                $tip = strtoupper(substr((string)($r['tipus'] ?? ''), 0, 4));
                if ($id <= $tol || $id > $ig || $kid <= 0 || !preg_match('/^[A-Z0-9]{0,4}$/', $tip)) {
                    throw new InvalidArgumentException('hibas naplosor');
                }
                $ins->execute([$hid, $id, $kid, $tip, pa_penz($r['osszeg'] ?? null),
                               pa_penz($r['elotte'] ?? null), pa_ido_ok($r['ido'] ?? ''), pa_now()]);
                $uj += $ins->rowCount();
            }
            // A kartyak "naplo szerinti" egyenlege: a legutolso mozgas utan.
            $kartyak = array_unique(array_map(function ($r) { return (int)$r['kartya']; }, $sorok));
            foreach ($kartyak as $kid) {
                pa_kartya_naplo_frissit($hid, $kid);
            }
            $db->commit();
        } catch (Throwable $e) {
            $db->rollBack();
            throw $e;
        }
        $elozo = (int)(pa_hely_get($hid, 'naplo_ig')['v'] ?? 0);
        pa_hely_set($hid, 'naplo_ig', (string)max($elozo, $ig));
        $info['uj_sor'] = $uj;
        $ki['naplo_ig'] = $ig;
    }

    if (isset($k['pillanatkep']) && is_array($k['pillanatkep'])) {
        $p = $k['pillanatkep'];
        $lista = $p['lista'] ?? null;
        if (!is_array($lista) || count($lista) > 20000) {
            throw new InvalidArgumentException('hibas pillanatkep');
        }
        $ido = pa_ido_ok($p['ido'] ?? '') ?? pa_now();
        $gen = isset($p['gen']) ? (int)$p['gen'] : null;
        $nevek = ($p['nevek'] ?? false) === true;
        $kulcs = pa_adat_kulcs() !== null;
        $db->beginTransaction();
        try {
            if (!$nevek) {
                $db->prepare('UPDATE kartya SET nev_titkos = NULL WHERE helyszin_id = ?')->execute([$hid]);
            }
            $up = $db->prepare('UPDATE kartya SET egyenleg = ?, egyenleg_ido = ?, egyenleg_gen = ?, ervenyes = ?
                                WHERE helyszin_id = ? AND kartya_id = ?');
            $ins = $db->prepare('INSERT INTO kartya (egyenleg, egyenleg_ido, egyenleg_gen, ervenyes, helyszin_id, kartya_id)
                                 VALUES (?, ?, ?, ?, ?, ?)');
            $nevup = $db->prepare('UPDATE kartya SET nev_titkos = ? WHERE helyszin_id = ? AND kartya_id = ?');
            foreach ($lista as $r) {
                $kid = (int)($r['id'] ?? 0);
                if ($kid <= 0) {
                    throw new InvalidArgumentException('hibas kartya-ID');
                }
                $row = [pa_penz($r['egyenleg'] ?? null), $ido, $gen, (int)!empty($r['ervenyes']), $hid, $kid];
                $up->execute($row);
                if ($up->rowCount() === 0) {
                    $ins->execute($row);
                }
                if ($nevek && $kulcs && isset($r['nev']) && is_string($r['nev'])) {
                    $nev = mb_substr(trim($r['nev']), 0, 40);
                    $nevup->execute([$nev === '' ? null : pa_titkosit($nev, pa_nev_cel($hid, $kid)), $hid, $kid]);
                }
            }
            $db->commit();
        } catch (Throwable $e) {
            $db->rollBack();
            throw $e;
        }
        $info['pillanatkep'] = $ido;
        $info['nevek'] = $nevek ? ($kulcs ? 'titkositva' : 'nincs adat_kulcs') : 'kikapcsolva';
        $info['kartyak'] = count($lista);
        $ki['pillanatkep_ok'] = true;
    }

    if (isset($k['egyeztetes']) && is_array($k['egyeztetes'])) {
        $e = $k['egyeztetes'];
        $tiszta = [
            'ido' => pa_ido_ok($e['ido'] ?? '') ?? pa_now(),
            'kartyak' => (int)($e['kartyak'] ?? 0),
            'naplo_nelkul' => (int)($e['naplo_nelkul'] ?? 0),
            'elteres' => [],
        ];
        foreach (array_slice((array)($e['elteres'] ?? []), 0, 200) as $r) {
            $tiszta['elteres'][] = ['kartya' => (int)($r['kartya'] ?? 0),
                                    'egyenleg' => pa_penz($r['egyenleg'] ?? null),
                                    'naplo_szerint' => pa_penz($r['naplo_szerint'] ?? null)];
        }
        pa_hely_set($hid, 'egyeztetes', json_encode($tiszta));
        $ki['egyeztetes_ok'] = true;
    }

    pa_hely_set($hid, 'kartya_info', json_encode($info));
    return $ki;
}

function pa_kartya_naplo_frissit(int $hid, int $kid): void
{
    $db = pa_db();
    $st = $db->prepare('SELECT naplo_id, osszeg, elotte, ido FROM kartyamozgas
                        WHERE helyszin_id = ? AND kartya_id = ? ORDER BY naplo_id DESC LIMIT 1');
    $st->execute([$hid, $kid]);
    $m = $st->fetch();
    if (!$m) {
        return;
    }
    $ne = number_format((float)$m['elotte'] + (float)$m['osszeg'], 2, '.', '');
    $row = [$ne, (int)$m['naplo_id'], $m['ido'], $hid, $kid];
    $up = $db->prepare('UPDATE kartya SET naplo_egyenleg = ?, utolso_naplo_id = ?, utolso_mozgas = ?
                        WHERE helyszin_id = ? AND kartya_id = ?');
    $up->execute($row);
    if ($up->rowCount() === 0) {
        $db->prepare('INSERT INTO kartya (naplo_egyenleg, utolso_naplo_id, utolso_mozgas, helyszin_id, kartya_id)
                      VALUES (?, ?, ?, ?, ?)')->execute($row);
    }
}

/**
 * Elter-e a kassza szerinti egyenleg a naplo szerintitol? Csak akkor
 * dontunk, ha a pillanatkep ota minden naplosor megerkezett.
 */
function pa_kartya_allapot(array $k, int $beerkezett_ig): string
{
    if ($k['egyenleg'] === null || $k['naplo_egyenleg'] === null) {
        return $k['naplo_egyenleg'] === null ? 'nincs mozgás' : '–';
    }
    if ($k['egyenleg_gen'] !== null && $beerkezett_ig < (int)$k['egyenleg_gen']) {
        return 'szinkron…';
    }
    return abs((float)$k['egyenleg'] - (float)$k['naplo_egyenleg']) < 0.005 ? 'ok' : 'eltér';
}

/** A titkositas "cimkeje": a nev csak ehhez a helyszinhez es kartyahoz tartozik. */
function pa_nev_cel(int $hid, int $kid): string
{
    return 'kartya-nev:' . $hid . ':' . $kid;
}

// ---- nevek megjelenitese az adminban -------------------------------------

const PA_NEV_TELJES_MP = 900;   // a teljes nev 15 percig latszik

/** 'rejtett' (csak csillag) | 'kezdo' (kezdobetu + csillag) | 'teljes' */
function pa_nev_mod(): string
{
    pa_session();
    $m = $_SESSION['nev_mod'] ?? 'rejtett';
    if ($m === 'teljes' && (int)($_SESSION['nev_teljes_ig'] ?? 0) < time()) {
        $m = $_SESSION['nev_mod'] = 'rejtett';
    }
    return in_array($m, ['rejtett', 'kezdo', 'teljes'], true) ? $m : 'rejtett';
}

function pa_nev_mod_beallit(string $m, string $user, string $hely): void
{
    pa_session();
    if (!in_array($m, ['rejtett', 'kezdo', 'teljes'], true)) {
        return;
    }
    $_SESSION['nev_mod'] = $m;
    if ($m === 'teljes') {
        $_SESSION['nev_teljes_ig'] = time() + PA_NEV_TELJES_MP;
        pa_audit($user, 'nevek_mutatva', $hely . ' (15 perc)');
    } else {
        unset($_SESSION['nev_teljes_ig']);
    }
}

function pa_nev_mutat(?string $titkos, int $hid, int $kid, string $mod): string
{
    if ($titkos === null) {
        return '';
    }
    if ($mod === 'rejtett') {
        return '*****';
    }
    $nev = pa_visszafejt($titkos, pa_nev_cel($hid, $kid));
    if ($nev === null) {
        return '(nem olvasható)';
    }
    if ($mod === 'teljes') {
        return $nev;
    }
    $szavak = preg_split('/\s+/u', trim($nev)) ?: [];
    return implode(' ', array_map(function ($w) {
        return mb_substr($w, 0, 1) . '***';
    }, $szavak));
}
