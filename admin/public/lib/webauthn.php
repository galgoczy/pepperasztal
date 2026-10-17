<?php
/**
 * Passkey (WebAuthn) - kulso konyvtar nelkul.
 *
 * Regisztracio: csak belepett felhasznalo (vagy az egyszeri beallito kod
 * utan) vehet fel passkey-t. Attesztaciot nem kerunk ("none"): a kulcs a
 * belepett felhasznalohoz kerul, a gyarto nem szamit.
 * Belepes: a bongeszo a sajat passkey-jei kozul valaszt (discoverable
 * credential), mi a nyilvanos kulccsal ellenorizzuk az alairast.
 *
 * Tamogatott algoritmusok: ES256 (-7, szinte minden eszkoz) es RS256
 * (-257, Windows Hello egy resze). Mindig kerjuk a felhasznalo
 * ellenorzeset (ujjlenyomat / arc / PIN).
 */

declare(strict_types=1);

require_once __DIR__ . '/google.php';   // pa_b64url, pa_b64url_dec

const PA_WA_TTL = 300;   // a challenge ervenyessege, mp

function pa_wa_rp_id(): string
{
    return (string)parse_url(pa_base_url(), PHP_URL_HOST);
}

function pa_wa_user_handle(string $user): string
{
    return substr(hash('sha256', 'pepperadmin:' . $user, true), 0, 16);
}

function pa_wa_challenge(string $mod, ?string $user): string
{
    pa_session();
    $c = random_bytes(32);
    $_SESSION['wa'] = ['c' => pa_b64url($c), 'mod' => $mod, 'u' => $user, 't' => time()];
    return pa_b64url($c);
}

/** A sessionben tarolt challenge-et egyszer lehet felhasznalni. */
function pa_wa_take(string $mod): ?array
{
    pa_session();
    $w = $_SESSION['wa'] ?? null;
    unset($_SESSION['wa']);
    if (!is_array($w) || $w['mod'] !== $mod || time() - (int)$w['t'] > PA_WA_TTL) {
        return null;
    }
    return $w;
}

function pa_wa_passkeys(string $user): array
{
    $st = pa_db()->prepare('SELECT * FROM passkey WHERE felhasznalo = ? ORDER BY id');
    $st->execute([$user]);
    return $st->fetchAll();
}

function pa_wa_register_options(string $user): array
{
    $excl = [];
    foreach (pa_wa_passkeys($user) as $p) {
        $excl[] = ['type' => 'public-key', 'id' => $p['cred_id']];
    }
    return [
        'challenge' => pa_wa_challenge('reg', $user),
        'rp' => ['id' => pa_wa_rp_id(), 'name' => 'Pepper Admin'],
        'user' => ['id' => pa_b64url(pa_wa_user_handle($user)), 'name' => $user,
                   'displayName' => $user],
        'pubKeyCredParams' => [['type' => 'public-key', 'alg' => -7],
                               ['type' => 'public-key', 'alg' => -257]],
        'authenticatorSelection' => ['residentKey' => 'required',
                                     'requireResidentKey' => true,
                                     'userVerification' => 'required'],
        'excludeCredentials' => $excl,
        'attestation' => 'none',
        'timeout' => PA_WA_TTL * 1000,
    ];
}

function pa_wa_login_options(): array
{
    return [
        'challenge' => pa_wa_challenge('be', null),
        'rpId' => pa_wa_rp_id(),
        'userVerification' => 'required',
        'timeout' => PA_WA_TTL * 1000,
    ];
}

// ---- CBOR (csak ami az attesztaciohoz es a COSE kulcshoz kell) -----------

/** Egy CBOR-elem dekodolasa $pos-tol; $pos az elem utanra lep. */
function pa_cbor(string $b, int &$pos, int $depth = 0)
{
    if ($depth > 8 || $pos >= strlen($b)) {
        throw new RuntimeException('CBOR: hibas adat');
    }
    $ib = ord($b[$pos++]);
    $mt = $ib >> 5;
    $ai = $ib & 0x1f;
    if ($ai < 24) {
        $val = $ai;
    } elseif ($ai <= 27) {
        $n = 1 << ($ai - 24);
        if ($pos + $n > strlen($b)) {
            throw new RuntimeException('CBOR: rovid adat');
        }
        $val = 0;
        for ($i = 0; $i < $n; $i++) {
            $val = ($val << 8) | ord($b[$pos++]);
        }
    } else {
        throw new RuntimeException('CBOR: nem tamogatott hossz');
    }
    switch ($mt) {
        case 0: return $val;
        case 1: return -1 - $val;
        case 2:
        case 3:
            if ($val < 0 || $pos + $val > strlen($b)) {
                throw new RuntimeException('CBOR: rovid adat');
            }
            $s = substr($b, $pos, $val);
            $pos += $val;
            return $s;
        case 4:
            $a = [];
            for ($i = 0; $i < $val; $i++) {
                $a[] = pa_cbor($b, $pos, $depth + 1);
            }
            return $a;
        case 5:
            $m = [];
            for ($i = 0; $i < $val; $i++) {
                $k = pa_cbor($b, $pos, $depth + 1);
                $m[$k] = pa_cbor($b, $pos, $depth + 1);
            }
            return $m;
        case 7:
            if ($val === 20) return false;
            if ($val === 21) return true;
            if ($val === 22) return null;
    }
    throw new RuntimeException('CBOR: nem tamogatott tipus');
}

function pa_der_len(int $n): string
{
    if ($n < 128) {
        return chr($n);
    }
    $s = '';
    while ($n > 0) {
        $s = chr($n & 0xff) . $s;
        $n >>= 8;
    }
    return chr(0x80 | strlen($s)) . $s;
}

function pa_der(int $tag, string $body): string
{
    return chr($tag) . pa_der_len(strlen($body)) . $body;
}

function pa_der_uint(string $bytes): string
{
    $bytes = ltrim($bytes, "\0");
    if ($bytes === '' || ord($bytes[0]) & 0x80) {
        $bytes = "\0" . $bytes;
    }
    return pa_der(0x02, $bytes);
}

/** COSE kulcs -> [PEM, alg]. */
function pa_cose_to_pem(array $k): array
{
    $alg = $k[3] ?? null;
    if (($k[1] ?? null) === 2 && $alg === -7 && ($k[-1] ?? null) === 1
            && strlen((string)($k[-2] ?? '')) === 32 && strlen((string)($k[-3] ?? '')) === 32) {
        $der = hex2bin('3059301306072a8648ce3d020106082a8648ce3d030107034200')
            . "\x04" . $k[-2] . $k[-3];
    } elseif (($k[1] ?? null) === 3 && $alg === -257 && is_string($k[-1] ?? null)
            && is_string($k[-2] ?? null) && strlen($k[-1]) >= 256) {
        $rsa = pa_der(0x30, pa_der_uint($k[-1]) . pa_der_uint($k[-2]));
        $der = pa_der(0x30, pa_der(0x30, hex2bin('06092a864886f70d010101') . "\x05\x00")
            . pa_der(0x03, "\0" . $rsa));
    } else {
        throw new RuntimeException('nem tamogatott kulcstipus');
    }
    $pem = "-----BEGIN PUBLIC KEY-----\n" . chunk_split(base64_encode($der), 64, "\n")
        . "-----END PUBLIC KEY-----\n";
    if (openssl_pkey_get_public($pem) === false) {
        throw new RuntimeException('ervenytelen nyilvanos kulcs');
    }
    return [$pem, (int)$alg];
}

// ---- ellenorzes --------------------------------------------------------

/** A clientDataJSON kozos ellenorzese; visszaadja a nyers bajtokat. */
function pa_wa_client_data(string $b64, string $type, string $challenge): string
{
    $raw = pa_b64url_dec($b64);
    $cd = json_decode($raw, true);
    if (!is_array($cd) || ($cd['type'] ?? '') !== $type) {
        throw new RuntimeException('rossz clientData tipus');
    }
    if (!hash_equals($challenge, (string)($cd['challenge'] ?? ''))) {
        throw new RuntimeException('challenge elteres');
    }
    if (($cd['origin'] ?? '') !== pa_base_url()) {
        throw new RuntimeException('rossz origin: ' . substr((string)($cd['origin'] ?? ''), 0, 80));
    }
    return $raw;
}

/** Az authenticatorData eleje: rpId hash, jelzok (UP + UV kotelezo), szamlalo. */
function pa_wa_auth_data(string $ad): array
{
    if (strlen($ad) < 37) {
        throw new RuntimeException('rovid authenticatorData');
    }
    if (!hash_equals(hash('sha256', pa_wa_rp_id(), true), substr($ad, 0, 32))) {
        throw new RuntimeException('rpId elteres');
    }
    $flags = ord($ad[32]);
    if (!($flags & 0x01) || !($flags & 0x04)) {
        throw new RuntimeException('nincs felhasznaloi jelenlet/ellenorzes');
    }
    return [$flags, unpack('N', substr($ad, 33, 4))[1]];
}

/** Uj passkey ellenorzese es mentese. Visszaadja a mentett nevet. */
function pa_wa_register(string $user, array $in, string $nev): string
{
    $w = pa_wa_take('reg');
    if (!$w || $w['u'] !== $user) {
        throw new RuntimeException('lejart vagy hianyzo challenge');
    }
    pa_wa_client_data((string)($in['clientDataJSON'] ?? ''), 'webauthn.create', $w['c']);
    $pos = 0;
    $att = pa_cbor(pa_b64url_dec((string)($in['attestationObject'] ?? '')), $pos);
    $ad = is_array($att) ? (string)($att['authData'] ?? '') : '';
    [$flags, $count] = pa_wa_auth_data($ad);
    if (!($flags & 0x40) || strlen($ad) < 55) {
        throw new RuntimeException('nincs kulcsadat');
    }
    $len = unpack('n', substr($ad, 53, 2))[1];
    $credId = substr($ad, 55, $len);
    if (strlen($credId) !== $len || $len < 16) {
        throw new RuntimeException('hibas kulcsazonosito');
    }
    if (!hash_equals(pa_b64url($credId), (string)($in['rawId'] ?? ''))) {
        throw new RuntimeException('kulcsazonosito elteres');
    }
    $credB64 = pa_b64url($credId);
    if (strlen($credB64) > 191) {
        throw new RuntimeException('tul hosszu kulcsazonosito');
    }
    $kpos = 55 + $len;
    $cose = pa_cbor($ad, $kpos);
    if (!is_array($cose)) {
        throw new RuntimeException('hibas COSE kulcs');
    }
    [$pem, $alg] = pa_cose_to_pem($cose);

    $nev = trim($nev);
    $nev = $nev !== '' ? mb_substr($nev, 0, 100) : 'passkey ' . date('Y-m-d');
    pa_db()->prepare('INSERT INTO passkey (felhasznalo, cred_id, kulcs, alg, szamlalo, nev, letrehozva)
                      VALUES (?, ?, ?, ?, ?, ?, ?)')
        ->execute([$user, $credB64, $pem, $alg, $count, $nev, pa_now()]);
    return $nev;
}

/** Belepes passkey-jel. Siker: a felhasznalonev. */
function pa_wa_login(array $in): string
{
    $w = pa_wa_take('be');
    if (!$w) {
        throw new RuntimeException('lejart vagy hianyzo challenge');
    }
    $id = (string)($in['rawId'] ?? '');
    $st = pa_db()->prepare('SELECT * FROM passkey WHERE cred_id = ?');
    $st->execute([$id]);
    $pk = $st->fetch();
    if (!$pk) {
        throw new RuntimeException('ismeretlen passkey');
    }
    $user = (string)$pk['felhasznalo'];
    if (!array_key_exists($user, pa_users())) {
        throw new RuntimeException('a felhasznalo mar nincs a konfiguracioban: ' . $user);
    }
    $uh = (string)($in['userHandle'] ?? '');
    if ($uh !== '' && !hash_equals(pa_b64url(pa_wa_user_handle($user)), $uh)) {
        throw new RuntimeException('userHandle elteres');
    }
    $cdRaw = pa_wa_client_data((string)($in['clientDataJSON'] ?? ''), 'webauthn.get', $w['c']);
    $ad = pa_b64url_dec((string)($in['authenticatorData'] ?? ''));
    [, $count] = pa_wa_auth_data($ad);
    $sig = pa_b64url_dec((string)($in['signature'] ?? ''));
    $ok = openssl_verify($ad . hash('sha256', $cdRaw, true), $sig, (string)$pk['kulcs'],
        OPENSSL_ALGO_SHA256);
    if ($ok !== 1) {
        throw new RuntimeException('hibas alairas');
    }
    // Ha a szamlalo nem no, a kulcsot lemasolhattak (a szinkronizalt
    // passkey-k mindig 0-t kuldenek - azt elfogadjuk).
    $old = (int)$pk['szamlalo'];
    if (($count !== 0 || $old !== 0) && $count <= $old) {
        throw new RuntimeException('a szamlalo nem nott (masolt kulcs?)');
    }
    pa_db()->prepare('UPDATE passkey SET szamlalo = ?, utoljara = ? WHERE id = ?')
        ->execute([$count, pa_now(), $pk['id']]);
    return $user;
}
