<?php
/** Belepes, majd a helyszinek attekintese. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$user = pa_user();

// ---- belepes ------------------------------------------------------------
if ($user === null) {
    $hiba = null;
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
        pa_check_csrf();
        if (pa_login_blocked()) {
            $hiba = 'Túl sok hibás próbálkozás. Próbáld újra 15 perc múlva.';
        } elseif (pa_login(trim((string)($_POST['u'] ?? '')), (string)($_POST['p'] ?? ''))) {
            pa_redirect('/');
        } else {
            $hiba = 'Hibás felhasználónév vagy jelszó.';
        }
    }
    pa_page_start('Belépés', null);
    echo '<div class="login"><h1>Belépés</h1>';
    if (!pa_users()) {
        echo '<div class="notice bad">Még nincs felhasználó beállítva. A <a href="/jelszo.php">jelszó-hash</a> '
            . 'oldalon készíts hash-t, és vedd fel a konfigurációba (<code>admin_users</code>).</div>';
    }
    if ($hiba) {
        echo '<div class="notice bad">' . h($hiba) . '</div>';
    }
    echo '<form method="post">' . pa_csrf_field()
        . '<input type="text" name="u" placeholder="Felhasználónév" autocomplete="username" required>'
        . '<input type="password" name="p" placeholder="Jelszó" autocomplete="current-password" required>'
        . '<button class="btn primary">Belépés</button></form></div>';
    pa_page_end();
    exit;
}

// ---- muveletek ----------------------------------------------------------
$db = pa_db();
$kiadasok = pa_kiadasok();
$legujabb = $kiadasok[0] ?? null;

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    $mit = (string)($_POST['mit'] ?? '');
    if ($mit === 'uj_helyszin') {
        $kulcs = trim((string)($_POST['kulcs'] ?? ''));
        $nev = trim((string)($_POST['nev'] ?? ''));
        if (!preg_match('/^[A-Za-z0-9]{2,64}$/', $kulcs) || $nev === '') {
            pa_flash('A kulcs csak betű és szám lehet (ékezet és szóköz nélkül), a név nem lehet üres.', 'bad');
        } else {
            [$token, $hash] = pa_new_token();
            try {
                $db->prepare('INSERT INTO helyszin (kulcs, nev, token_hash, token_letrehozva, letrehozva)
                              VALUES (?, ?, ?, ?, ?)')
                    ->execute([$kulcs, mb_substr($nev, 0, 100), $hash, pa_now(), pa_now()]);
                pa_audit($user, 'helyszin_uj', $kulcs);
                pa_flash('Helyszín felvéve: ' . h($nev) . '<br>' . pa_token_notice($kulcs, $token));
            } catch (Throwable $e) {
                pa_flash('Ilyen kulcsú helyszín már van.', 'bad');
            }
        }
    } elseif ($mit === 'frissit_mind' && $legujabb) {
        $db->prepare('UPDATE helyszin SET cel_verzio = ? WHERE token_hash IS NOT NULL')
            ->execute([$legujabb['verzio']]);
        pa_audit($user, 'frissites_mind', $legujabb['verzio']);
        pa_flash('Minden helyszín célverziója: ' . h($legujabb['verzio'])
            . '. A gépek a következő jelentésnél (kb. 1 perc) frissülnek.');
    }
    pa_redirect('/');
}

// ---- attekintes ---------------------------------------------------------
$rows = $db->query('SELECT h.*, j.ido, j.gep, j.agent_verzio, j.adat
                    FROM helyszin h LEFT JOIN jelentes j ON j.helyszin_id = h.id
                    ORDER BY h.nev')->fetchAll();

pa_page_start('Helyszínek', $user, 30);
pa_show_flash();
?>
<h1>Helyszínek</h1>
<p class="sub">Életjel percenként. Zöld: 3 percen belül, sárga: 15 percen belül.
Az oldal 30 másodpercenként frissül.</p>

<div class="card scroll"><table>
<tr><th>Helyszín</th><th>Életjel</th><th>Ügynök</th><th>Adatbázis</th>
    <th>Éjszakai mentés</th><th>Napközbeni</th></tr>
<?php if (!$rows): ?>
<tr><td colspan="6" class="muted">Még nincs helyszín. Lent vehetsz fel újat.</td></tr>
<?php endif; ?>
<?php foreach ($rows as $r):
    $a = pa_json($r['adat']);
    $m = $a['mentes'] ?? [];
    $dbs = $a['db'] ?? [];
    $elet = pa_age_class($r['ido'], 180, 900);
    $ej = pa_age_class($m['utolso_mentes'] ?? null, 26 * 3600, 30 * 3600);
    $ver = $r['agent_verzio'];
    $cel = $r['cel_verzio'];
?>
<tr>
  <td><a href="/helyszin.php?id=<?= (int)$r['id'] ?>"><strong><?= h($r['nev']) ?></strong></a>
      <div class="muted mono"><?= h($r['kulcs']) ?><?= $r['token_hash'] ? '' : ' · <span class="bad">nincs token</span>' ?></div></td>
  <td class="<?= $elet ?>"><span class="dot"></span><?= h(pa_ago($r['ido'])) ?>
      <div class="muted"><?= h($r['gep']) ?></div></td>
  <td class="mono"><?= h($ver ?: '–') ?>
      <?php if ($cel && $ver && pa_ver_cmp($cel, $ver) > 0): ?><div class="warn">→ <?= h($cel) ?> folyamatban</div><?php endif; ?>
      <?php if (!empty($a['frissites']['eredmeny'])): ?><div class="muted"><?= h($a['frissites']['eredmeny']) ?></div><?php endif; ?></td>
  <td class="<?= !$r['ido'] ? 'muted' : (!empty($dbs['ok']) ? 'ok' : 'bad') ?>">
      <?= !$r['ido'] ? '–' : (!empty($dbs['ok']) ? 'elérhető' : 'HIBA') ?>
      <?php if (isset($dbs['naplo_gen'])): ?><div class="muted">napló #<?= (int)$dbs['naplo_gen'] ?></div><?php endif; ?></td>
  <td class="<?= $r['ido'] ? $ej : 'muted' ?>"><?= h(pa_ago($m['utolso_mentes'] ?? null)) ?>
      <?php if (!empty($m['archiv_meret_mb'])): ?><div class="muted"><?= h((string)$m['archiv_meret_mb']) ?> MB</div><?php endif; ?>
      <?php if (!empty($m['utolso_hiba'])): ?><div class="bad">hiba: <?= h(mb_substr((string)$m['utolso_hiba'], 0, 80)) ?></div><?php endif; ?></td>
  <td><?= h(pa_ago($m['utolso_napkozbeni'] ?? null)) ?>
      <?php if (!empty($m['utolso_napkozbeni_kihagyva'])): ?><div class="muted">kihagyva: <?= h(substr((string)$m['utolso_napkozbeni_kihagyva'], 11, 5)) ?></div><?php endif; ?></td>
</tr>
<?php endforeach; ?>
</table></div>

<h2>Ügynök-frissítés</h2>
<?php if ($legujabb): ?>
<div class="notice">
  Elérhető aláírt kiadás: <strong class="mono"><?= h($legujabb['verzio']) ?></strong>
  <span class="muted">(<?= h($legujabb['ido'] ?? '') ?>, <?= (int)round(($legujabb['meret'] ?? 0) / 1024) ?> KB)</span>
  <div class="row" style="margin-top:10px">
    <form method="post" class="inline" data-confirm="Minden helyszín frissüljön erre: <?= h($legujabb['verzio']) ?>?">
      <?= pa_csrf_field() ?><input type="hidden" name="mit" value="frissit_mind">
      <button class="btn">Frissítés minden helyszínen</button></form>
    <span class="muted">Egyenként a helyszín oldalán is lehet – ajánlott előbb egy helyen kipróbálni.</span>
  </div>
</div>
<?php else: ?>
<div class="notice">Nincs aláírt kiadás a szerveren. Az aláíró kulcs beállítása után a GitHub Action
minden ügynök-változásnál feltölt egyet (lásd <code>admin/README.md</code>).</div>
<?php endif; ?>

<h2>Új helyszín</h2>
<form method="post" class="row">
  <?= pa_csrf_field() ?><input type="hidden" name="mit" value="uj_helyszin">
  <input type="text" name="kulcs" placeholder="Kulcs, pl. RSR" pattern="[A-Za-z0-9]{2,64}" required>
  <input type="text" name="nev" placeholder="Megjelenő név, pl. RSR" required>
  <button class="btn primary">Felvétel és token</button>
</form>
<p class="muted">A kulcs egyezzen a gép <code>pepper_agent.ini</code>-jében lévő <code>helyszin</code> értékkel.</p>
<?php
pa_page_end();
