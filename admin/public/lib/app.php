<?php
/** Az admin oldalak kozos betoltese. */

declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
require __DIR__ . '/schema.php';
require __DIR__ . '/auth.php';
require __DIR__ . '/kiadas.php';
require_once __DIR__ . '/google.php';
require __DIR__ . '/ui.php';

if (!pa_config_path()) {
    // Konfiguracio nelkul csak az allapotoldal ertelmes.
    header('Location: /allapot.php');
    exit;
}
pa_migrate();

function pa_flash(?string $msg = null, string $cls = 'ok'): ?array
{
    pa_session();
    if ($msg !== null) {
        $_SESSION['flash'] = [$msg, $cls];
        return null;
    }
    $f = $_SESSION['flash'] ?? null;
    unset($_SESSION['flash']);
    return $f;
}

function pa_show_flash(): void
{
    $f = pa_flash();
    if ($f) {
        echo '<div class="notice ' . h($f[1]) . '">' . $f[0] . '</div>';
    }
}

function pa_redirect(string $to): void
{
    header('Location: ' . $to);
    exit;
}

/** Uj token: 32 veletlen bajt hexben. Csak a hash-e marad meg. */
function pa_new_token(): array
{
    $t = bin2hex(random_bytes(32));
    return [$t, hash('sha256', $t)];
}

function pa_token_notice(string $kulcs, string $token): string
{
    return '<strong>Az új token – most látod utoljára, másold ki:</strong>'
        . '<pre class="mono">[felho]
url = https://' . h($_SERVER['HTTP_HOST'] ?? 'pepperadmin.zentopia.io') . '
helyszin = ' . h($kulcs) . '
token = ' . h($token) . '</pre>'
        . 'A POS gépen a <code>pepper_agent.ini</code>-be kerül. Utána a '
        . '<code>python jelentes.py --titkosit</code> DPAPI-val titkosítja, és a nyílt '
        . '<code>token</code> sor törölhető.';
}
