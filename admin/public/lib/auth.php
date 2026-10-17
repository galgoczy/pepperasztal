<?php
/**
 * Belepes az admin feluletre - Google-fiokkal vagy passkey-jel. Jelszavas
 * belepes nincs.
 *
 * Ki lephet be: a konfiguracio admin_users resze, nev => Google e-mail:
 *   'admin_users' => ['gergely' => 'valaki@gmail.com'],
 * Aki innen kikerul, az se Google-lel, se a korabbi passkey-eivel nem lep
 * be tobbe.
 *
 * Vedelmek: biztonsagos session-suti (HTTPS, HttpOnly, SameSite=Strict),
 * session-azonosito csere belepeskor, 8 oras tetlensegi kileptetes, CSRF
 * token minden POST-hoz, es IP-nkent legfeljebb 5 sikertelen belepes 15
 * percenkent.
 */

declare(strict_types=1);

const PA_LOGIN_MAX = 5;
const PA_LOGIN_WINDOW = 900;      // mp
const PA_IDLE = 8 * 3600;         // mp

function pa_https(): bool
{
    return (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
}

function pa_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    session_name('pa_sess');
    session_set_cookie_params([
        'lifetime' => 0, 'path' => '/', 'secure' => pa_https(),
        'httponly' => true, 'samesite' => 'Strict',
    ]);
    session_start();
    if (isset($_SESSION['user'], $_SESSION['seen'])
            && time() - $_SESSION['seen'] > PA_IDLE) {
        $_SESSION = [];
        session_regenerate_id(true);
    }
    if (isset($_SESSION['user'])) {
        $_SESSION['seen'] = time();
    }
}

/** nev => e-mail. A regi jelszo-hash ertekek e-mail nelkulinek szamitanak. */
function pa_users(): array
{
    $u = pa_config()['admin_users'] ?? [];
    $out = [];
    foreach (is_array($u) ? $u : [] as $nev => $v) {
        $email = is_string($v) && strpos($v, '@') !== false ? strtolower(trim($v)) : null;
        $out[(string)$nev] = $email;
    }
    return $out;
}

/** Van-e meg a konfiguracioban regi, jelszo-hash formaju felhasznalo. */
function pa_users_legacy(): array
{
    return array_keys(array_filter(pa_users(), function ($e) { return $e === null; }));
}

function pa_user_by_email(string $email): ?string
{
    $email = strtolower(trim($email));
    foreach (pa_users() as $nev => $e) {
        if ($e !== null && hash_equals($e, $email)) {
            return $nev;
        }
    }
    return null;
}

function pa_user(): ?string
{
    pa_session();
    $u = $_SESSION['user'] ?? null;
    return ($u !== null && array_key_exists($u, pa_users())) ? $u : null;
}

function pa_client_ip(): string
{
    return substr((string)($_SERVER['REMOTE_ADDR'] ?? '?'), 0, 45);
}

/**
 * A sajat cim: https://<host>. Ha a konfiguracioban van base_url, az az
 * irany (a Host fejlecet a kliens kuldi); a Google- es a passkey-ellenorzes
 * is ehhez a cimhez kotott.
 */
function pa_base_url(): string
{
    $b = (string)(pa_config()['base_url'] ?? '');
    if ($b === '') {
        $b = (pa_https() ? 'https://' : 'http://') . ($_SERVER['HTTP_HOST'] ?? 'localhost');
    }
    return rtrim($b, '/');
}

function pa_login_blocked(): bool
{
    // A regi probalkozasok nem kellenek - a tabla ne nojon vegtelenul.
    pa_db()->prepare('DELETE FROM login_proba WHERE ido < ?')
        ->execute([date('Y-m-d H:i:s', time() - 86400)]);
    $since = date('Y-m-d H:i:s', time() - PA_LOGIN_WINDOW);
    $st = pa_db()->prepare('SELECT COUNT(*) FROM login_proba WHERE ip = ? AND ido >= ?');
    $st->execute([pa_client_ip(), $since]);
    return (int)$st->fetchColumn() >= PA_LOGIN_MAX;
}

/** Sikertelen belepes: szamlalo + naplo. $ki: amit tudunk (e-mail, '?'). */
function pa_login_fail(string $ki, string $ok): void
{
    pa_db()->prepare('INSERT INTO login_proba (ip, ido) VALUES (?, ?)')
        ->execute([pa_client_ip(), pa_now()]);
    pa_audit(mb_substr($ki !== '' ? $ki : '?', 0, 64), 'belepes_hiba',
        pa_client_ip() . ' ' . $ok);
    usleep(300000);
}

/** Sikeres azonositas utan: uj session-azonosito, felhasznalo a sessionbe. */
function pa_login_as(string $user, string $mod): void
{
    pa_session();
    session_regenerate_id(true);
    $flash = $_SESSION['flash'] ?? null;
    $_SESSION = ['user' => $user, 'seen' => time()];
    if ($flash) {
        $_SESSION['flash'] = $flash;
    }
    pa_audit($user, 'belepes', $mod . ' ' . pa_client_ip());
}

function pa_logout(): void
{
    pa_session();
    $u = $_SESSION['user'] ?? null;
    if ($u) {
        pa_audit($u, 'kilepes');
    }
    $_SESSION = [];
    session_regenerate_id(true);
}

function pa_require_login(): string
{
    $u = pa_user();
    if ($u === null) {
        header('Location: /');
        exit;
    }
    return $u;
}

function pa_csrf(): string
{
    pa_session();
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['csrf'];
}

function pa_csrf_field(): string
{
    return '<input type="hidden" name="csrf" value="' . pa_csrf() . '">';
}

function pa_check_csrf(): void
{
    pa_session();
    $t = (string)($_POST['csrf'] ?? $_SERVER['HTTP_X_CSRF'] ?? '');
    if ($t === '' || !hash_equals($_SESSION['csrf'] ?? '', $t)) {
        http_response_code(400);
        exit('Ervenytelen urlap (CSRF). Toltsd ujra az oldalt.');
    }
}
