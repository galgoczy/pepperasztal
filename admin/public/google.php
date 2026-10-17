<?php
/** Belepes Google-fiokkal: indulas (parameter nelkul) es visszateres (?state, ?code / ?error). */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

if (!pa_google_cfg()) {
    pa_redirect('/');
}
if (!isset($_GET['state'])) {
    if (pa_login_blocked()) {
        pa_flash('Túl sok sikertelen belépés. Próbáld újra 15 perc múlva.', 'bad');
        pa_redirect('/');
    }
    pa_google_start();
}

[$user, $ok] = pa_google_callback();
if ($user === null) {
    pa_login_fail('google', $ok);
    pa_flash('A Google-belépés nem sikerült, vagy ez a fiók nem léphet be.', 'bad');
} else {
    pa_login_as($user, 'google');
}

// Nem Location-fejleccel iranyitunk tovabb: a Google-tol indult lanc
// vegen a bongeszo meg nem kuldene a SameSite=Strict session-sutit, es
// kileptetettnek latszana. Egy sajat oldalrol inditott ujratoltes mar igen.
pa_security_headers();
header('Cache-Control: no-store');
echo '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/">'
    . '<title>Pepper Admin</title><a href="/">Tovább</a>';
