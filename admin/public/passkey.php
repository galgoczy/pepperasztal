<?php
/** A belepett felhasznalo passkey-jei: lista, uj felvetele, torles. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';
require __DIR__ . '/lib/webauthn.php';

$user = pa_require_login();

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    if (($_POST['mit'] ?? '') === 'torol') {
        $st = pa_db()->prepare('SELECT nev FROM passkey WHERE id = ? AND felhasznalo = ?');
        $st->execute([(int)($_POST['id'] ?? 0), $user]);
        $nev = $st->fetchColumn();
        if ($nev !== false) {
            pa_db()->prepare('DELETE FROM passkey WHERE id = ? AND felhasznalo = ?')
                ->execute([(int)$_POST['id'], $user]);
            pa_audit($user, 'passkey_torles', (string)$nev);
            pa_flash('Passkey törölve: ' . h((string)$nev) . '. Az eszközön is törölheted.');
        }
    }
    pa_redirect('/passkey.php');
}

$lista = pa_wa_passkeys($user);
$email = pa_users()[$user] ?? null;
pa_page_start('Passkeyek', $user);
pa_show_flash();
?>
<h1>Passkeyek</h1>
<p class="sub">Belépés ujjlenyomattal, arccal vagy PIN-nel, jelszó nélkül. A passkey az
eszközödön (vagy a jelszókezelődben) van; a szerveren csak a nyilvános kulcs.
<?php if ($email && pa_google_cfg()): ?>Google-fiókkal is beléphetsz: <strong><?= h($email) ?></strong>.<?php endif; ?></p>

<?php if (!$lista): ?>
<div class="notice">Még nincs passkey-d. Vegyél fel legalább egyet – ha a Google-belépés
egyszer nem elérhető, ezzel akkor is be tudsz lépni.</div>
<?php else: ?>
<table>
  <thead><tr><th>Név</th><th>Felvéve</th><th>Utoljára használva</th><th></th></tr></thead>
  <tbody>
  <?php foreach ($lista as $p): ?>
    <tr>
      <td><?= h($p['nev']) ?></td>
      <td><?= h($p['letrehozva']) ?></td>
      <td><?= $p['utoljara'] ? h(pa_ago($p['utoljara'])) : 'még nem' ?></td>
      <td><form method="post" data-confirm="Biztosan törlöd ezt a passkey-t: <?= h($p['nev']) ?>?">
        <?= pa_csrf_field() ?><input type="hidden" name="mit" value="torol">
        <input type="hidden" name="id" value="<?= (int)$p['id'] ?>">
        <button class="btn danger">Törlés</button></form></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>

<h2>Új passkey ezen az eszközön</h2>
<form data-passkey-reg class="row">
  <input type="text" name="nev" placeholder="Eszköz neve, pl. Gergely iPhone" maxlength="100">
  <button class="btn primary">Passkey létrehozása</button>
</form>
<div class="notice bad" data-passkey-msg hidden></div>
<?php
pa_page_end();
