<?php
/**
 * Szemelyes adat (most: a feltoltos kartyak neve) titkositasa az
 * adatbazisban. AES-256-GCM, a kulcs a konfiguracio 'adat_kulcs' sora
 * (64 hexa karakter) - NEM az adatbazisban, igy egy kiszivargott
 * adatbazis-mentesbol a nevek nem olvashatok.
 *
 * Kulcs keszitese: php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"
 * Ha a kulcs elveszik, a tarolt nevek nem fejthetok vissza - a gepek a
 * kovetkezo pillanatkepnel ujra felkuldik oket.
 */

declare(strict_types=1);

function pa_adat_kulcs(): ?string
{
    $k = (string)(pa_config()['adat_kulcs'] ?? '');
    return preg_match('/^[0-9a-f]{64}$/i', $k) ? hex2bin($k) : null;
}

function pa_titkosit(string $s, string $cel): ?string
{
    $k = pa_adat_kulcs();
    if ($k === null) {
        return null;
    }
    $iv = random_bytes(12);
    $tag = '';
    $ct = openssl_encrypt($s, 'aes-256-gcm', $k, OPENSSL_RAW_DATA, $iv, $tag, $cel);
    return $ct === false ? null : 'v1:' . base64_encode($iv . $tag . $ct);
}

function pa_visszafejt(?string $s, string $cel): ?string
{
    $k = pa_adat_kulcs();
    if ($k === null || $s === null || strncmp($s, 'v1:', 3) !== 0) {
        return null;
    }
    $b = base64_decode(substr($s, 3), true);
    if ($b === false || strlen($b) < 28) {
        return null;
    }
    $pt = openssl_decrypt(substr($b, 28), 'aes-256-gcm', $k, OPENSSL_RAW_DATA,
        substr($b, 0, 12), substr($b, 12, 16), $cel);
    return $pt === false ? null : $pt;
}
