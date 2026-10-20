<?php
/**
 * Feltoltos kartyak: a gepek jelentesenek "kartyak" resze (agent/kartyak.py).
 *
 *   naplo:       { tol, ig, sorok: [{id, kartya, tipus, osszeg, elotte, ido}] }
 *   pillanatkep: { ido, gen, nevek, kodok, lista: [{id, egyenleg, ervenyes, nev?, kod?}] }
 *                (a kod a kartyakod, a vonalkod-oldalhoz; titkositva, kodok = false
 *                eseten a tarolt kodok torlodnek)
 *                (a nev titkositva kerul az adatbazisba; nevek = false eseten
 *                a helyszin minden tarolt nevet toroljuk)
 *   egyeztetes:  { ido, kartyak, naplo_nelkul, elteres: [...] }
 *   vasarlasok:  [{ naplo_id, nyugta, kartya, ido, osszeg, vegertek,
 *                   tetelek: [{nev, menny, ertek, kat_id, kat}] }]
 *   azonositasok: { tol, ig, lista: [{ nyugta, kartya, ido, vegertek, tetelek }] }
 *                (kartya csak azonositasra: 0 Ft-os VIP-sor, a fizetes mas modon)
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
        $kodok = ($p['kodok'] ?? false) === true;
        $kulcs = pa_adat_kulcs() !== null;
        $db->beginTransaction();
        try {
            if (!$nevek) {
                $db->prepare('UPDATE kartya SET nev_titkos = NULL WHERE helyszin_id = ?')->execute([$hid]);
            }
            if (!$kodok) {
                $db->prepare('UPDATE kartya SET kod_titkos = NULL WHERE helyszin_id = ?')->execute([$hid]);
            }
            $kodup = $db->prepare('UPDATE kartya SET kod_titkos = ? WHERE helyszin_id = ? AND kartya_id = ?');
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
                if ($kodok && $kulcs) {
                    $kod = $r['kod'] ?? null;
                    $kod = is_string($kod) && preg_match('/^[\x20-\x7e]{1,20}$/', $kod) ? $kod : null;
                    $kodup->execute([$kod === null ? null : pa_titkosit($kod, pa_kod_cel($hid, $kid)), $hid, $kid]);
                }
            }
            $db->commit();
        } catch (Throwable $e) {
            $db->rollBack();
            throw $e;
        }
        $info['pillanatkep'] = $ido;
        $info['nevek'] = $nevek ? ($kulcs ? 'titkositva' : 'nincs adat_kulcs') : 'kikapcsolva';
        $info['kodok'] = $kodok ? ($kulcs ? 'titkositva' : 'nincs adat_kulcs') : 'kikapcsolva';
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

    if (isset($k['vasarlasok']) && is_array($k['vasarlasok'])) {
        // Kulon kezelve: egy hibas vasarlas ne tartsa vissza a naplo
        // visszaigazolasat (a gep akkor ujra kuldene mindent).
        try {
            $ki['vasarlas_ok'] = pa_vasarlasok_fogad($hid, $k['vasarlasok']);
            $info['vasarlas'] = count($ki['vasarlas_ok']);
        } catch (Throwable $e) {
            $info['vasarlas_hiba'] = mb_substr($e->getMessage(), 0, 200);
        }
    }

    if (isset($k['azonositasok']) && is_array($k['azonositasok'])) {
        $a = $k['azonositasok'];
        $ig = (int)($a['ig'] ?? -1);
        if ($ig < 0 || !is_array($a['lista'] ?? null) || count($a['lista']) > 500) {
            $a = ['lista' => []];
            $ig = -1;
            $info['azonositas_hiba'] = 'hibas azonositas-resz';
        }
        // Kulon kezelve, mint a vasarlasok: ne tartsa vissza a naplot.
        try {
            $info['azonositas'] = pa_azonositasok_fogad($hid, $a['lista']);
            $ki['azonositas_ig'] = $ig;
        } catch (Throwable $e) {
            $info['azonositas_hiba'] = mb_substr($e->getMessage(), 0, 200);
        }
    }
    if (isset($k['azonositas_hiba'])) {
        $info['azonositas_hiba'] = 'gep: ' . mb_substr((string)$k['azonositas_hiba'], 0, 200);
    }

    pa_hely_set($hid, 'kartya_info', json_encode($info));
    return $ki;
}

/** A tetelek ellenorzott, rovidebb alakja (vasarlas es azonositas). */
function pa_tetelek_tiszta($lista): array
{
    if (!is_array($lista)) {
        throw new InvalidArgumentException('hibas tetelek');
    }
    $ki = [];
    foreach (array_slice($lista, 0, 100) as $t) {
        $ki[] = [
            'nev' => mb_substr((string)($t['nev'] ?? ''), 0, 60),
            'menny' => round((float)($t['menny'] ?? 0), 3),
            'ertek' => pa_penz($t['ertek'] ?? null),
            'kat_id' => isset($t['kat_id']) ? (int)$t['kat_id'] : null,
            'kat' => mb_substr((string)($t['kat'] ?? ''), 0, 40),
        ];
    }
    return $ki;
}

/** Kartya csak azonositasra: mentes (nyugta + kartya szerint egyedi). */
function pa_azonositasok_fogad(int $hid, array $lista): int
{
    $db = pa_db();
    $ins = $db->prepare(pa_beszur_ignore() . ' INTO kartyaazonositas
        (helyszin_id, nyugta_id, kartya_id, ido, vegertek, tetelek, erkezett)
        VALUES (?, ?, ?, ?, ?, ?, ?)');
    $uj = 0;
    $db->beginTransaction();
    try {
        foreach ($lista as $v) {
            $fej = (int)($v['nyugta'] ?? 0);
            $kid = (int)($v['kartya'] ?? 0);
            if ($fej <= 0 || $kid <= 0) {
                throw new InvalidArgumentException('hibas azonositas');
            }
            $ins->execute([$hid, $fej, $kid, pa_ido_ok($v['ido'] ?? ''), pa_penz($v['vegertek'] ?? null),
                           json_encode(pa_tetelek_tiszta($v['tetelek'] ?? []), JSON_UNESCAPED_UNICODE), pa_now()]);
            $uj += $ins->rowCount();
        }
        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }
    return $uj;
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

/** A kartyakod titkositasanak kotott adata (mas kartya soraba masolva nem fejtheto vissza). */
function pa_kod_cel(int $hid, int $kid): string
{
    return 'kartya-kod:' . $hid . ':' . $kid;
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

/** A vasarlasok mentese; visszaadja a mentett (vagy mar meglevo) naplo-ID-ket. */
function pa_vasarlasok_fogad(int $hid, array $lista): array
{
    if (count($lista) > 500) {
        throw new InvalidArgumentException('tul sok vasarlas');
    }
    $db = pa_db();
    $ins = $db->prepare(pa_beszur_ignore() . ' INTO kartyavasarlas
        (helyszin_id, naplo_id, nyugta_id, kartya_id, ido, osszeg, vegertek, tetelek)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
    $ok = [];
    $db->beginTransaction();
    try {
        foreach ($lista as $v) {
            $nid = (int)($v['naplo_id'] ?? 0);
            $fej = (int)($v['nyugta'] ?? 0);
            $kid = (int)($v['kartya'] ?? 0);
            if ($nid <= 0 || $fej <= 0 || $kid <= 0 || !is_array($v['tetelek'] ?? null)) {
                throw new InvalidArgumentException('hibas vasarlas');
            }
            $tetelek = [];
            foreach (array_slice($v['tetelek'], 0, 100) as $t) {
                $tetelek[] = [
                    'nev' => mb_substr((string)($t['nev'] ?? ''), 0, 60),
                    'menny' => round((float)($t['menny'] ?? 0), 3),
                    'ertek' => pa_penz($t['ertek'] ?? null),
                    'kat_id' => isset($t['kat_id']) ? (int)$t['kat_id'] : null,
                    'kat' => mb_substr((string)($t['kat'] ?? ''), 0, 40),
                ];
            }
            $ins->execute([$hid, $nid, $fej, $kid, pa_ido_ok($v['ido'] ?? ''),
                           pa_penz($v['osszeg'] ?? null), pa_penz($v['vegertek'] ?? null),
                           json_encode($tetelek, JSON_UNESCAPED_UNICODE)]);
            $ok[] = $nid;
        }
        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }
    return $ok;
}

/** "1x Napi Menü, 2x Cappuccino" - a 0 erteku menu-osszetevok nelkul. */
function pa_tetelek_szoveg(?string $json): string
{
    $t = json_decode((string)$json, true);
    if (!is_array($t)) {
        return '';
    }
    $ki = [];
    foreach ($t as $x) {
        if ((float)($x['ertek'] ?? 0) == 0.0 && count($t) > 1) {
            continue;
        }
        $m = (float)($x['menny'] ?? 1);
        $ki[] = ($m == (int)$m ? (int)$m : $m) . '× ' . ($x['nev'] ?? '');
    }
    return implode(', ', $ki);
}
