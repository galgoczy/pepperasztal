<?php
/**
 * Passkey felvetele Google-belepes nelkul, egy egyszeri beallito koddal.
 *
 * Csak akkor mukodik, ha a konfiguracioban van legalabb 20 karakteres
 * 'setup_code'. A felhasznalonev + kod utan 10 percig lehet passkey-t
 * letrehozni, ami egyben be is leptet. Utana a setup_code sort torold.
 */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$kod = (string)(pa_config()['setup_code'] ?? '');
if (pa_user() !== null || strlen($kod) < 20) {
    pa_redirect('/');
}

$hiba = null;
$kesz = isset($_SESSION['setup_user'], $_SESSION['setup_t'])
    && time() - (int)$_SESSION['setup_t'] < 600;
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    $u = trim((string)($_POST['u'] ?? ''));
    if (pa_login_blocked()) {
        $hiba = 'Túl sok sikertelen próbálkozás. Próbáld újra 15 perc múlva.';
    } elseif (array_key_exists($u, pa_users()) && hash_equals($kod, (string)($_POST['k'] ?? ''))) {
        session_regenerate_id(true);
        $_SESSION['setup_user'] = $u;
        $_SESSION['setup_t'] = time();
        pa_audit($u, 'beallito_kod', pa_client_ip());
        $kesz = true;
    } else {
        pa_login_fail($u, 'beallito kod');
        $hiba = 'Hibás felhasználónév vagy kód.';
    }
}

pa_page_start('Első passkey', null);
echo '<div class="login"><h1>Első passkey</h1>';
if ($hiba) {
    echo '<div class="notice bad">' . h($hiba) . '</div>';
}
if ($kesz) {
    echo '<p class="sub">Szia, ' . h((string)$_SESSION['setup_user']) . '! Hozd létre a passkey-t '
        . 'ezen az eszközön (ujjlenyomat, arc vagy PIN). Utána be leszel lépve.</p>'
        . '<form data-passkey-reg>'
        . '<input type="text" name="nev" placeholder="Eszköz neve, pl. Gergely iPhone" maxlength="100">'
        . '<button class="btn primary">Passkey létrehozása</button></form>'
        . '<div class="notice bad" data-passkey-msg hidden></div>';
} else {
    echo '<p class="sub">A konfigurációban megadott <code>setup_code</code>-dal.</p>'
        . '<form method="post">' . pa_csrf_field()
        . '<input type="text" name="u" placeholder="Felhasználónév (admin_users)" autocomplete="username" required>'
        . '<input type="password" name="k" placeholder="Beállító kód" autocomplete="off" required>'
        . '<button class="btn primary">Tovább</button></form>';
}
echo '</div>';
pa_page_end();
