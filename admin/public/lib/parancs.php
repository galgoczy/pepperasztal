<?php
/**
 * Utasitasok a POS gepnek - jelenleg: egyenleg-modositas (feltoltes / levonas)
 * egy feltoltos kartyan. A gep csak akkor hajtja vegre, ha az ini-jeben
 * [iras] be = igen all (agent/iras.py).
 *
 * Elet: var -> kuldve (a gep megkapta) -> kesz / hiba. A 10 percnel
 * regebbi, meg le nem futott utasitast nem kuldjuk ki tobbet (lejart) -
 * egy hosszan offline gep ne hajtson vegre kesobb varatlanul egy regi
 * feltoltest. Ha megis lefutott, a gep eredmenye felulirja.
 */

declare(strict_types=1);

const PA_PARANCS_LEJAR = 600;   // mp

function pa_parancs_uj(int $hid, int $kid, float $osszeg, string $megj, string $user): int
{
    $db = pa_db();
    $db->prepare('INSERT INTO parancs (helyszin_id, tipus, kartya_id, osszeg, megjegyzes, letrehozta,
                  letrehozva, allapot) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
        ->execute([$hid, 'egyenleg', $kid, number_format($osszeg, 2, '.', ''),
                   mb_substr($megj, 0, 200), $user, pa_now(), 'var']);
    return (int)$db->lastInsertId();
}

/** A gepnek kuldendo utasitasok (es a lejartak megjelolese). */
function pa_parancs_kiad(int $hid): array
{
    $db = pa_db();
    $hatar = date('Y-m-d H:i:s', time() - PA_PARANCS_LEJAR);
    $db->prepare("UPDATE parancs SET allapot = 'lejart', frissitve = ? WHERE helyszin_id = ?
                  AND allapot IN ('var', 'kuldve') AND letrehozva < ?")
        ->execute([pa_now(), $hid, $hatar]);
    $st = $db->prepare("SELECT id, tipus, kartya_id, osszeg FROM parancs WHERE helyszin_id = ?
                        AND allapot IN ('var', 'kuldve') ORDER BY id LIMIT 20");
    $st->execute([$hid]);
    $ki = [];
    foreach ($st->fetchAll() as $r) {
        $ki[] = ['id' => (int)$r['id'], 'tipus' => $r['tipus'], 'kartya' => (int)$r['kartya_id'],
                 'osszeg' => (float)$r['osszeg']];
    }
    if ($ki) {
        $db->prepare("UPDATE parancs SET allapot = 'kuldve', kuldve = ? WHERE helyszin_id = ?
                      AND allapot = 'var'")->execute([pa_now(), $hid]);
    }
    return $ki;
}

/** A gep eredmenyei; visszaadja a visszaigazolt utasitas-ID-ket. */
function pa_parancs_eredmeny(int $hid, string $hely, array $lista): array
{
    $db = pa_db();
    $up = $db->prepare('UPDATE parancs SET allapot = ?, eredmeny = ?, frissitve = ?
                        WHERE id = ? AND helyszin_id = ?');
    $ack = [];
    foreach (array_slice($lista, 0, 100) as $e) {
        $id = (int)($e['id'] ?? 0);
        if ($id <= 0) {
            continue;
        }
        $ok = !empty($e['ok']);
        $tiszta = [
            'ok' => $ok,
            'hiba' => isset($e['hiba']) ? mb_substr((string)$e['hiba'], 0, 300) : null,
            'naplo_id' => isset($e['naplo_id']) ? (int)$e['naplo_id'] : null,
            'egyenleg' => isset($e['egyenleg']) ? pa_penz((string)$e['egyenleg']) : null,
            'elotte' => isset($e['elotte']) ? pa_penz((string)$e['elotte']) : null,
        ];
        $up->execute([$ok ? 'kesz' : 'hiba', json_encode($tiszta, JSON_UNESCAPED_UNICODE),
                      pa_now(), $id, $hid]);
        if ($up->rowCount() > 0) {
            pa_audit('gep:' . $hely, $ok ? 'egyenleg_kesz' : 'egyenleg_hiba',
                     '#' . $id . ' ' . ($ok ? 'egyenleg ' . $tiszta['egyenleg'] : $tiszta['hiba']));
        }
        $ack[] = $id;
    }
    return $ack;
}
