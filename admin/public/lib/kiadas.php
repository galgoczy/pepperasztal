<?php
/**
 * Ugynok-kiadasok. A CI (deploy-admin.yml) epiti es irja ala a csomagot,
 * es a kiadasok/ mappaba tolti fel: agent-<verzio>.zip + agent-<verzio>.json.
 * A szerver NEM tud alairni - a privat kulcs csak a GitHub secretben van.
 * A kiadasok/ mappa kozvetlenul nem toltheto le; a gepek az
 * /api/frissites.php-n at, tokennel kapjak meg.
 */

declare(strict_types=1);

function pa_kiadas_dir(): string
{
    return dirname(__DIR__) . '/kiadasok';
}

/** '2026-10-17.4' -> [2026, 10, 17, 4] - szamszeru osszehasonlitashoz. */
function pa_ver_parts(string $v): array
{
    preg_match_all('/\d+/', $v, $m);
    return array_map('intval', $m[0]);
}

function pa_ver_cmp(string $a, string $b): int
{
    return pa_ver_parts($a) <=> pa_ver_parts($b);
}

/** Az elerheto (alairt) kiadasok, legujabb elol. */
function pa_kiadasok(): array
{
    $out = [];
    foreach (glob(pa_kiadas_dir() . '/agent-*.json') ?: [] as $f) {
        $m = json_decode((string)file_get_contents($f), true);
        if (!is_array($m) || empty($m['verzio']) || empty($m['sig'])) {
            continue;
        }
        $zip = pa_kiadas_dir() . '/agent-' . $m['verzio'] . '.zip';
        if (!is_file($zip)) {
            continue;
        }
        $m['zip'] = $zip;
        $out[] = $m;
    }
    usort($out, fn($x, $y) => pa_ver_cmp($y['verzio'], $x['verzio']));
    return $out;
}

function pa_kiadas(string $verzio): ?array
{
    foreach (pa_kiadasok() as $k) {
        if ($k['verzio'] === $verzio) {
            return $k;
        }
    }
    return null;
}
