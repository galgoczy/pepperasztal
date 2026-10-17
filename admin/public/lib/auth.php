<?php
/**
 * Belepes az admin feluletre.
 *
 * A felhasznalok a konfiguracioban vannak, jelszo-hash-sel:
 *   'admin_users' => ['gergely' => '$2y$10$...'],
 * Hash-t a /jelszo.php oldal general (nem tarol semmit).
 *
 * Vedelmek: biztonsagos session-suti (HTTPS, HttpOnly, SameSite=Strict),
 * session-azonosito csere belepeskor, 8 oras tetlensegi kileptetes, CSRF
 * token minden POST-hoz, es IP-nkent legfeljebb 5 hibas probalkozas 15
 * percenkent.
 */

declare(strict_types=1);

const PA_LOGIN_MAX = 5;
const PA_LOGIN_WINDOW = 900;      // mp
const PA_IDLE = 8 * 3600;         // mp

function pa_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    session_name('pa_sess');
    session_set_cookie_params([
        'lifetime' => 0, 'path' => '/', 'secure' => $https,
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

function pa_users(): array
{
    $u = pa_config()['admin_users'] ?? [];
    return is_array($u) ? $u : [];
}

function pa_user(): ?string
{
    pa_session();
    $u = $_SESSION['user'] ?? null;
    return ($u !== null && isset(pa_users()[$u])) ? $u : null;
}

function pa_client_ip(): string
{
    return substr((string)($_SERVER['REMOTE_ADDR'] ?? '?'), 0, 45);
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

/** true = sikeres belepes. Hibanal a hivo egysegesen "hibas adatok"-at mutat. */
function pa_login(string $user, string $pass): bool
{
    if (pa_login_blocked()) {
        return false;
    }
    $users = pa_users();
    $hash = $users[$user] ?? null;
    // Nem letezo felhasznalonal is fusson egy password_verify, hogy az
    // idozitesbol ne derulhessen ki, mely nevek leteznek.
    $ok = password_verify($pass, $hash ?? '$2y$10$8j/y6EdCYWlMfyyTulmTUeEllhlWrowXJrylxTFqiwx3rgoXKvUaO');
    if ($hash === null || !$ok) {
        pa_db()->prepare('INSERT INTO login_proba (ip, ido) VALUES (?, ?)')
            ->execute([pa_client_ip(), pa_now()]);
        pa_audit($user !== '' ? mb_substr($user, 0, 64) : '?', 'belepes_hiba', pa_client_ip());
        usleep(400000);
        return false;
    }
    session_regenerate_id(true);
    $_SESSION['user'] = $user;
    $_SESSION['seen'] = time();
    pa_audit($user, 'belepes', pa_client_ip());
    return true;
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
    $t = (string)($_POST['csrf'] ?? '');
    if ($t === '' || !hash_equals($_SESSION['csrf'] ?? '', $t)) {
        http_response_code(400);
        exit('Ervenytelen urlap (CSRF). Toltsd ujra az oldalt.');
    }
}
