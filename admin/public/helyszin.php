<?php
/** Egy helyszin reszletei: token, celverzio, utolso jelentes. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$user = pa_require_login();
$db = pa_db();
$id = (int)($_GET['id'] ?? $_POST['id'] ?? 0);
$st = $db->prepare('SELECT h.*, j.ido, j.ip, j.gep, j.agent_verzio, j.adat
                    FROM helyszin h LEFT JOIN jelentes j ON j.helyszin_id = h.id WHERE h.id = ?');
$st->execute([$id]);
$s = $st->fetch();
if (!$s) {
    http_response_code(404);
    exit('Nincs ilyen helyszín.');
}
$kiadasok = pa_kiadasok();
$self = '/helyszin.php?id=' . $id;

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    $mit = (string)($_POST['mit'] ?? '');
    if ($mit === 'uj_token') {
        [$token, $hash] = pa_new_token();
        $db->prepare('UPDATE helyszin SET token_hash = ?, token_letrehozva = ? WHERE id = ?')
            ->execute([$hash, pa_now(), $id]);
        pa_audit($user, 'token_uj', $s['kulcs']);
        pa_flash('Új token készült, a régi azonnal érvénytelen.<br>' . pa_token_notice($s['kulcs'], $token));
    } elseif ($mit === 'token_vissza') {
        $db->prepare('UPDATE helyszin SET token_hash = NULL WHERE id = ?')->execute([$id]);
        pa_audit($user, 'token_visszavonva', $s['kulcs']);
        pa_flash('A token visszavonva – a gép nem tud jelenteni, amíg új tokent nem kap.');
    } elseif ($mit === 'cel') {
        $v = (string)($_POST['verzio'] ?? '');
        if ($v === '') {
            $db->prepare('UPDATE helyszin SET cel_verzio = NULL WHERE id = ?')->execute([$id]);
            pa_audit($user, 'cel_torolve', $s['kulcs']);
            pa_flash('Célverzió törölve – a gép nem frissül.');
        } elseif (pa_kiadas($v)) {
            $db->prepare('UPDATE helyszin SET cel_verzio = ? WHERE id = ?')->execute([$v, $id]);
            pa_audit($user, 'cel_beallitva', $s['kulcs'] . ' -> ' . $v);
            pa_flash('Célverzió: ' . h($v) . '. A gép a következő jelentésnél (kb. 1 perc) frissül.');
        }
    } elseif ($mit === 'atnevez') {
        $nev = trim((string)($_POST['nev'] ?? ''));
        if ($nev !== '') {
            $db->prepare('UPDATE helyszin SET nev = ? WHERE id = ?')->execute([mb_substr($nev, 0, 100), $id]);
            pa_audit($user, 'atnevezve', $s['kulcs'] . ' -> ' . $nev);
        }
    } elseif ($mit === 'torles' && ($_POST['megerosit'] ?? '') === $s['kulcs']) {
        $db->prepare('DELETE FROM jelentes WHERE helyszin_id = ?')->execute([$id]);
        $db->prepare('DELETE FROM helyszin WHERE id = ?')->execute([$id]);
        pa_audit($user, 'helyszin_torolve', $s['kulcs']);
        pa_flash('Helyszín törölve: ' . h($s['nev']));
        pa_redirect('/');
    }
    pa_redirect($self);
}

$a = pa_json($s['adat']);
$m = $a['mentes'] ?? [];
pa_page_start($s['nev'], $user);
pa_show_flash();
?>
<h1><?= h($s['nev']) ?> <span class="chip mono"><?= h($s['kulcs']) ?></span></h1>
<p class="sub">Utolsó jelentés: <span class="<?= pa_age_class($s['ido'], 180, 900) ?>"><?= h(pa_ago($s['ido'])) ?></span>
<?php if ($s['ido']): ?> · <?= h($s['ido']) ?> · gép: <?= h($s['gep']) ?> · IP: <?= h($s['ip']) ?><?php endif; ?></p>

<div class="card"><table>
<tr><th>Ügynök verzió</th><td class="mono"><?= h($s['agent_verzio'] ?: '–') ?></td></tr>
<tr><th>Célverzió</th><td>
  <form method="post" class="row"><?= pa_csrf_field() ?><input type="hidden" name="mit" value="cel">
    <select name="verzio">
      <option value="">– nincs (nem frissül) –</option>
      <?php foreach ($kiadasok as $k): ?>
      <option value="<?= h($k['verzio']) ?>" <?= $s['cel_verzio'] === $k['verzio'] ? 'selected' : '' ?>><?= h($k['verzio']) ?></option>
      <?php endforeach; ?>
    </select>
    <button class="btn">Mentés</button>
    <?php if ($s['cel_verzio'] && !pa_kiadas($s['cel_verzio'])): ?>
      <span class="warn">A beállított <?= h($s['cel_verzio']) ?> már nincs a szerveren.</span>
    <?php endif; ?>
  </form></td></tr>
<?php if (!empty($a['frissites'])): ?>
<tr><th>Utolsó frissítési kísérlet</th><td><?= h(($a['frissites']['ido'] ?? '') . ' – ' . ($a['frissites']['eredmeny'] ?? '')) ?></td></tr>
<?php endif; ?>
<tr><th>Adatbázis</th><td><?= !empty($a['db']['ok']) ? '<span class="ok">elérhető</span>' : '<span class="bad">' . h($a['db']['hiba'] ?? 'nincs adat') . '</span>' ?></td></tr>
<tr><th>Éjszakai mentés</th><td><?= h(($m['utolso_mentes'] ?? '–') . (isset($m['archiv_meret_mb']) ? ' · ' . $m['archiv_meret_mb'] . ' MB' : '')) ?></td></tr>
<tr><th>Napközbeni mentés</th><td><?= h($m['utolso_napkozbeni'] ?? '–') ?>
  <?php if (!empty($m['utolso_napkozbeni_kihagyva'])): ?><span class="muted"> · utoljára kihagyva: <?= h($m['utolso_napkozbeni_kihagyva']) ?></span><?php endif; ?></td></tr>
<tr><th>Mentési hiba</th><td class="<?= empty($m['utolso_hiba']) ? 'ok' : 'bad' ?>"><?= h($m['utolso_hiba'] ?? 'nincs') ?></td></tr>
<tr><th>Külső másolat</th><td><?= h(isset($m['masolat_ok']) ? ($m['masolat_ok'] === null ? 'nincs beállítva' : ($m['masolat_ok'] ? 'rendben' : 'HIBA')) : '–') ?></td></tr>
</table></div>

<?php if (!empty($m['mentesek'])): ?>
<h2>Visszaállítási pontok a gépen</h2>
<div class="card scroll"><table>
<tr><th>Napi</th><th>Heti</th><th>Napközbeni</th></tr>
<tr><?php foreach (['napi', 'heti', 'napkozbeni'] as $d): ?>
  <td class="mono"><?= implode('<br>', array_map('h', $m['mentesek'][$d] ?? [])) ?: '–' ?></td>
<?php endforeach; ?></tr>
</table></div>
<p class="muted">Visszaállítás innen szándékosan nem indítható – az kézzel, a gépen történik.</p>
<?php endif; ?>

<h2>Token</h2>
<p class="muted">Létrehozva: <?= h($s['token_letrehozva'] ?? '–') ?><?= $s['token_hash'] ? '' : ' · <span class="bad">nincs érvényes token</span>' ?></p>
<div class="row">
  <form method="post" class="inline" data-confirm="Új token? A régi azonnal érvénytelen lesz, a gépen is cserélni kell.">
    <?= pa_csrf_field() ?><input type="hidden" name="mit" value="uj_token"><button class="btn">Új token</button></form>
  <form method="post" class="inline" data-confirm="Visszavonod a tokent? A gép nem tud jelenteni.">
    <?= pa_csrf_field() ?><input type="hidden" name="mit" value="token_vissza"><button class="btn danger">Token visszavonása</button></form>
</div>

<h2>Utolsó jelentés (nyers)</h2>
<div class="card"><pre class="mono"><?= h($s['adat'] ? json_encode($a, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : '–') ?></pre></div>

<h2>Beállítások</h2>
<form method="post" class="row"><?= pa_csrf_field() ?><input type="hidden" name="mit" value="atnevez">
  <input type="text" name="nev" value="<?= h($s['nev']) ?>"><button class="btn">Átnevezés</button></form>
<form method="post" class="row" style="margin-top:12px"><?= pa_csrf_field() ?><input type="hidden" name="mit" value="torles">
  <input type="text" name="megerosit" placeholder="Törléshez írd be: <?= h($s['kulcs']) ?>">
  <button class="btn danger">Helyszín törlése</button></form>
<?php
pa_page_end();
