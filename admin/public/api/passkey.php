<?php
/**
 * Passkey-muveletek az admin oldalak JavaScriptje szamara (JSON).
 *
 *   POST ?mit=reg_opciok   uj passkey: opciok (belepve, vagy beallito kod utan)
 *   POST ?mit=reg_kesz     uj passkey: a bongeszo valasza
 *   POST ?mit=be_opciok    belepes: opciok
 *   POST ?mit=be_kesz      belepes: a bongeszo valasza
 *
 * Mindegyikhez kell az X-CSRF fejlec (az oldal session-tokenje).
 */

declare(strict_types=1);
require dirname(__DIR__) . '/lib/app.php';
require dirname(__DIR__) . '/lib/webauthn.php';

pa_security_headers();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function pa_out(int $code, array $d): void
{
    http_response_code($code);
    echo json_encode($d, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    pa_out(405, ['ok' => false, 'hiba' => 'csak POST']);
}
pa_session();
$csrf = (string)($_SERVER['HTTP_X_CSRF'] ?? '');
if ($csrf === '' || !hash_equals($_SESSION['csrf'] ?? '', $csrf)) {
    pa_out(400, ['ok' => false, 'hiba' => 'Lejárt az oldal, töltsd újra.']);
}
$in = json_decode((string)file_get_contents('php://input', false, null, 0, 65536), true);
$in = is_array($in) ? $in : [];
$mit = (string)($_GET['mit'] ?? '');

// Ki vehet fel passkey-t: a belepett felhasznalo, vagy aki az egyszeri
// beallito koddal most azonositotta magat (lasd elso-passkey.php).
$user = pa_user();
$setup = null;
if ($user === null && isset($_SESSION['setup_user'], $_SESSION['setup_t'])
        && time() - (int)$_SESSION['setup_t'] < 600
        && array_key_exists($_SESSION['setup_user'], pa_users())) {
    $setup = (string)$_SESSION['setup_user'];
}
$regUser = $user ?? $setup;

try {
    switch ($mit) {
        case 'reg_opciok':
            if ($regUser === null) {
                pa_out(403, ['ok' => false, 'hiba' => 'Előbb lépj be.']);
            }
            pa_out(200, ['ok' => true, 'opciok' => pa_wa_register_options($regUser)]);

        case 'reg_kesz':
            if ($regUser === null) {
                pa_out(403, ['ok' => false, 'hiba' => 'Előbb lépj be.']);
            }
            $nev = pa_wa_register($regUser, (array)($in['cred'] ?? []), (string)($in['nev'] ?? ''));
            pa_audit($regUser, 'passkey_uj', $nev . ($setup ? ' (beallito koddal)' : ''));
            if ($setup !== null) {
                unset($_SESSION['setup_user'], $_SESSION['setup_t']);
                pa_login_as($setup, 'beallito kod + uj passkey');
                pa_flash('Passkey felvéve, be vagy lépve. A <code>setup_code</code> sort most már '
                    . 'törölheted a konfigurációból.');
            } else {
                pa_flash('Passkey felvéve: ' . h($nev));
            }
            pa_out(200, ['ok' => true]);

        case 'be_opciok':
            if (pa_login_blocked()) {
                pa_out(429, ['ok' => false, 'hiba' => 'Túl sok sikertelen belépés. Próbáld újra 15 perc múlva.']);
            }
            pa_out(200, ['ok' => true, 'opciok' => pa_wa_login_options()]);

        case 'be_kesz':
            if (pa_login_blocked()) {
                pa_out(429, ['ok' => false, 'hiba' => 'Túl sok sikertelen belépés. Próbáld újra 15 perc múlva.']);
            }
            try {
                $u = pa_wa_login((array)($in['cred'] ?? []));
            } catch (Throwable $e) {
                pa_login_fail('passkey', $e->getMessage());
                pa_out(403, ['ok' => false, 'hiba' => 'Ezzel a passkey-jel nem lehet belépni.']);
            }
            pa_login_as($u, 'passkey');
            pa_out(200, ['ok' => true]);
    }
    pa_out(400, ['ok' => false, 'hiba' => 'ismeretlen művelet']);
} catch (Throwable $e) {
    error_log('pepperadmin passkey: ' . $e->getMessage());
    pa_audit($regUser ?? '?', 'passkey_hiba', $mit . ': ' . $e->getMessage());
    pa_out(400, ['ok' => false, 'hiba' => 'A passkey-t nem sikerült ellenőrizni.']);
}
