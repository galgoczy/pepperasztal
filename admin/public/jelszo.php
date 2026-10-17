<?php
/**
 * Jelszo-hash keszito az admin_users beallitashoz. Semmit nem tarol.
 * Amig nincs egyetlen felhasznalo sem, belepes nelkul is elerheto (igy
 * lehet az elsot letrehozni); utana csak belepve.
 */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$user = pa_users() ? pa_require_login() : null;
$hash = null;
$hiba = null;
$nev = '';
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    $nev = trim((string)($_POST['u'] ?? ''));
    $p1 = (string)($_POST['p1'] ?? '');
    $p2 = (string)($_POST['p2'] ?? '');
    if (!preg_match('/^[a-z0-9._-]{2,32}$/', $nev)) {
        $hiba = 'A felhasználónév kisbetű, szám, pont, kötőjel lehet (2–32).';
    } elseif (strlen($p1) < 12) {
        $hiba = 'A jelszó legalább 12 karakter legyen.';
    } elseif ($p1 !== $p2) {
        $hiba = 'A két jelszó nem egyezik.';
    } else {
        $hash = password_hash($p1, PASSWORD_DEFAULT);
    }
}
pa_page_start('Jelszó-hash', $user);
?>
<h1>Jelszó-hash</h1>
<p class="sub">A konfigurációs fájl <code>admin_users</code> részébe kerül. Az oldal semmit nem ment el.</p>
<?php if ($hiba): ?><div class="notice bad"><?= h($hiba) ?></div><?php endif; ?>
<?php if ($hash): ?>
<div class="notice ok">Ezt a sort tedd a konfiguráció <code>'admin_users' =&gt; [ ... ]</code> részébe:
<pre class="mono">'<?= h($nev) ?>' => '<?= h($hash) ?>',</pre></div>
<?php endif; ?>
<form method="post" style="display:grid;gap:10px;max-width:360px">
  <?= pa_csrf_field() ?>
  <input type="text" name="u" placeholder="Felhasználónév" value="<?= h($nev) ?>" required>
  <input type="password" name="p1" placeholder="Jelszó (min. 12 karakter)" autocomplete="new-password" required>
  <input type="password" name="p2" placeholder="Jelszó újra" autocomplete="new-password" required>
  <button class="btn primary">Hash készítése</button>
</form>
<?php
pa_page_end();
