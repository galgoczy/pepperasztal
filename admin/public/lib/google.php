<?php
/**
 * Belepes Google-fiokkal (OpenID Connect, authorization code + PKCE).
 *
 * Konfiguracio:
 *   'google' => ['client_id' => '...apps.googleusercontent.com',
 *                'client_secret' => '...'],
 * A Google Cloud Console-ban az engedelyezett atiranyitasi cim:
 *   https://pepperadmin.zentopia.io/google.php
 *
 * Az id_token-t kozvetlenul a Google token-vegpontjatol kapjuk TLS-en, igy
 * az alairasat nem kell kulon ellenorizni (OIDC Core 3.1.3.7); a kiadot, a
 * cimzettet, a lejaratot, a nonce-t es az e-mail megerositeset igen.
 */

declare(strict_types=1);

const PA_G_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth';
const PA_G_TOKEN = 'https://oauth2.googleapis.com/token';
const PA_G_COOKIE = 'pa_goauth';

function pa_google_cfg(): ?array
{
    $g = pa_config()['google'] ?? null;
    if (!is_array($g) || empty($g['client_id']) || empty($g['client_secret'])) {
        return null;
    }
    return $g;
}

function pa_google_redirect_uri(): string
{
    return pa_base_url() . '/google.php';
}

function pa_b64url(string $bin): string
{
    return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
}

function pa_b64url_dec(string $s): string
{
    $r = base64_decode(strtr($s, '-_', '+/') . str_repeat('=', (4 - strlen($s) % 4) % 4), true);
    return $r === false ? '' : $r;
}

/**
 * A Google-hoz iranyit. A state/nonce/PKCE egy kulon, rovid eletu, Lax
 * sutiben van: a session-suti Strict, azt a Google-tol visszatero keres
 * nem hozza magaval.
 */
function pa_google_start(): void
{
    $g = pa_google_cfg();
    $st = ['s' => pa_b64url(random_bytes(24)), 'n' => pa_b64url(random_bytes(24)),
           'v' => pa_b64url(random_bytes(48)), 't' => time()];
    setcookie(PA_G_COOKIE, pa_b64url(json_encode($st)), [
        'expires' => time() + 600, 'path' => '/google.php', 'secure' => pa_https(),
        'httponly' => true, 'samesite' => 'Lax',
    ]);
    $q = http_build_query([
        'client_id' => $g['client_id'],
        'redirect_uri' => pa_google_redirect_uri(),
        'response_type' => 'code',
        'scope' => 'openid email',
        'state' => $st['s'],
        'nonce' => $st['n'],
        'code_challenge' => pa_b64url(hash('sha256', $st['v'], true)),
        'code_challenge_method' => 'S256',
        'prompt' => 'select_account',
    ]);
    header('Location: ' . PA_G_AUTH . '?' . $q);
    exit;
}

function pa_http_post_form(string $url, array $fields): array
{
    $body = http_build_query($fields);
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body,
            CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15,
            CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
        ]);
        $resp = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
    } else {
        $ctx = stream_context_create(['http' => [
            'method' => 'POST', 'timeout' => 15, 'ignore_errors' => true,
            'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
            'content' => $body,
        ]]);
        $resp = @file_get_contents($url, false, $ctx);
        $code = 0;
        foreach ($http_response_header ?? [] as $hdr) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $hdr, $m)) {
                $code = (int)$m[1];
            }
        }
    }
    $d = is_string($resp) ? json_decode($resp, true) : null;
    return [$code, is_array($d) ? $d : []];
}

/**
 * A visszateres feldolgozasa. Siker: [felhasznalonev, null]; hiba:
 * [null, ok] - az ok a naploba megy, a felhasznalo egysegesen "nem
 * sikerult"-et lat.
 */
function pa_google_callback(): array
{
    $g = pa_google_cfg();
    $raw = (string)($_COOKIE[PA_G_COOKIE] ?? '');
    setcookie(PA_G_COOKIE, '', ['expires' => 1, 'path' => '/google.php',
        'secure' => pa_https(), 'httponly' => true, 'samesite' => 'Lax']);
    $st = json_decode(pa_b64url_dec($raw), true);
    if (!is_array($st) || empty($st['s']) || time() - (int)($st['t'] ?? 0) > 600) {
        return [null, 'nincs vagy lejart a state'];
    }
    if (!hash_equals($st['s'], (string)($_GET['state'] ?? ''))) {
        return [null, 'state elteres'];
    }
    if (isset($_GET['error'])) {
        return [null, 'google: ' . substr((string)$_GET['error'], 0, 60)];
    }
    $code = (string)($_GET['code'] ?? '');
    if ($code === '') {
        return [null, 'nincs code'];
    }
    [$http, $tok] = pa_http_post_form(PA_G_TOKEN, [
        'code' => $code,
        'client_id' => $g['client_id'],
        'client_secret' => $g['client_secret'],
        'redirect_uri' => pa_google_redirect_uri(),
        'grant_type' => 'authorization_code',
        'code_verifier' => $st['v'],
    ]);
    $idt = (string)($tok['id_token'] ?? '');
    $parts = explode('.', $idt);
    if ($http !== 200 || count($parts) !== 3) {
        return [null, 'token-csere hiba (HTTP ' . $http . ' ' . substr((string)($tok['error'] ?? ''), 0, 40) . ')'];
    }
    $c = json_decode(pa_b64url_dec($parts[1]), true);
    if (!is_array($c)) {
        return [null, 'olvashatatlan id_token'];
    }
    if (!in_array($c['iss'] ?? '', ['https://accounts.google.com', 'accounts.google.com'], true)) {
        return [null, 'rossz kiado'];
    }
    $aud = $c['aud'] ?? '';
    if (!(is_string($aud) ? hash_equals($g['client_id'], $aud) : in_array($g['client_id'], (array)$aud, true))) {
        return [null, 'rossz cimzett'];
    }
    if ((int)($c['exp'] ?? 0) < time() - 60) {
        return [null, 'lejart id_token'];
    }
    if (!hash_equals($st['n'], (string)($c['nonce'] ?? ''))) {
        return [null, 'nonce elteres'];
    }
    $email = (string)($c['email'] ?? '');
    if ($email === '' || ($c['email_verified'] ?? false) !== true) {
        return [null, 'nincs megerositett e-mail'];
    }
    $user = pa_user_by_email($email);
    if ($user === null) {
        return [null, 'nem engedelyezett: ' . $email];
    }
    return [$user, null];
}
