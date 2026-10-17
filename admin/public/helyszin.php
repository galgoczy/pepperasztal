<?php
/** Egy helyszin reszletei: token, celverzio, utolso jelentes. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';
require __DIR__ . '/lib/kartyak.php';

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
    } elseif ($mit === 'nevmod') {
        pa_nev_mod_beallit((string)($_POST['mod'] ?? ''), $user, $s['kulcs']);
        pa_redirect($self . '#kartyak');
    } elseif ($mit === 'atnevez') {
        $nev = trim((string)($_POST['nev'] ?? ''));
        if ($nev !== '') {
            $db->prepare('UPDATE helyszin SET nev = ? WHERE id = ?')->execute([mb_substr($nev, 0, 100), $id]);
            pa_audit($user, 'atnevezve', $s['kulcs'] . ' -> ' . $nev);
        }
    } elseif ($mit === 'torles' && ($_POST['megerosit'] ?? '') === $s['kulcs']) {
        foreach (['jelentes', 'kartya', 'kartyamozgas', 'helyszin_allapot'] as $t) {
            $db->prepare("DELETE FROM $t WHERE helyszin_id = ?")->execute([$id]);
        }
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

<?php
$kinfo = json_decode((string)(pa_hely_get($id, 'kartya_info')['v'] ?? ''), true) ?: [];
$egy = pa_hely_get($id, 'egyeztetes');
$egyd = $egy ? (json_decode((string)$egy['v'], true) ?: []) : [];
$ig = (int)(pa_hely_get($id, 'naplo_ig')['v'] ?? 0);
$kst = $db->prepare('SELECT k.*, (SELECT COUNT(*) FROM kartyamozgas m WHERE m.helyszin_id = k.helyszin_id
                     AND m.kartya_id = k.kartya_id) AS mozgas FROM kartya k WHERE k.helyszin_id = ?
                     ORDER BY k.utolso_mozgas DESC, k.kartya_id');
$kst->execute([$id]);
$kartyak = $kst->fetchAll();
$mst = $db->prepare('SELECT * FROM kartyamozgas WHERE helyszin_id = ? ORDER BY naplo_id DESC LIMIT 30');
$mst->execute([$id]);
$mozgasok = $mst->fetchAll();
?>
<h2 id="kartyak">Feltöltős kártyák</h2>
<?php
$nmod = pa_nev_mod();
$van_nev = (bool)array_filter($kartyak, function ($k) { return $k['nev_titkos'] !== null; });
?>
<p class="sub">Kártya-ID a helyszín NovoHostjában. A név titkosítva van tárolva, a kártyakód nem jön fel.
<?php if ($kinfo): ?>
  Napló: <?= (int)($kinfo['kurzor'] ?? 0) ?> / <?= h((string)($kinfo['gen'] ?? '?')) ?> sor-ID
  <?php if (isset($kinfo['gen'], $kinfo['kurzor']) && $kinfo['gen'] > $kinfo['kurzor']): ?>
    <span class="warn">· előzmény feltöltése folyamatban</span><?php endif; ?>
  <?php if (!empty($kinfo['pillanatkep'])): ?> · egyenlegek: <?= h((string)$kinfo['pillanatkep']) ?><?php endif; ?>
<?php else: ?>A gép még nem küldött kártyaadatot (ügynök 2026-10-17.9 vagy újabb kell).<?php endif; ?>
<?php if (!empty($kinfo['hiba'])): ?><br><span class="bad">Hiba a gépen: <?= h((string)$kinfo['hiba']) ?></span><?php endif; ?></p>

<?php if ($egyd): ?>
<p>Napi egyeztetés (<?= h($egyd['ido'] ?? '') ?>): <?= (int)($egyd['kartyak'] ?? 0) ?> kártya,
<?php if (empty($egyd['elteres'])): ?><span class="ok">mind egyezik a naplóval</span>
<?php else: ?><span class="bad"><?= count($egyd['elteres']) ?> eltér</span>
  (<?= h(implode(', ', array_map(function ($e) {
      return 'ID ' . $e['kartya'] . ': ' . $e['egyenleg'] . ' / napló ' . $e['naplo_szerint']; }, $egyd['elteres']))) ?>)
<?php endif; ?>
<?php if (!empty($egyd['naplo_nelkul'])): ?> · <?= (int)$egyd['naplo_nelkul'] ?> kártyának nincs naplósora<?php endif; ?></p>
<?php endif; ?>

<?php if (pa_adat_kulcs() === null): ?>
<div class="notice">A nevek tárolásához a konfigurációba kell egy titkosító kulcs, pl.:
<pre class="mono">'adat_kulcs' => '<?= bin2hex(random_bytes(32)) ?>',</pre>
Ezt a sort (ezzel vagy egy saját, 64 hexa karakteres értékkel) tedd a <code>pepperadmin-config.php</code>-ba.
A kulcs csak a szerveren legyen; ha elveszik, a gépek a neveket újra felküldik.</div>
<?php elseif (!empty($kinfo['nevek']) && $kinfo['nevek'] === 'kikapcsolva'): ?>
<p class="muted">A gépen a nevek küldése ki van kapcsolva (<code>[kartyak] nevek = nem</code>).</p>
<?php endif; ?>

<?php if ($van_nev): ?>
<form method="post" class="row" style="margin-bottom:10px"><?= pa_csrf_field() ?><input type="hidden" name="mit" value="nevmod">
  <span class="muted">Nevek:</span>
  <button class="btn<?= $nmod === 'rejtett' ? ' primary' : '' ?>" name="mod" value="rejtett">Rejtve</button>
  <button class="btn<?= $nmod === 'kezdo' ? ' primary' : '' ?>" name="mod" value="kezdo">Kezdőbetű</button>
  <button class="btn<?= $nmod === 'teljes' ? ' primary' : '' ?>" name="mod" value="teljes">Teljes (15 perc)</button>
  <?php if ($nmod === 'teljes'): ?><span class="warn">még <?= max(1, (int)ceil(((int)$_SESSION['nev_teljes_ig'] - time()) / 60)) ?> percig, a megtekintés naplózva</span><?php endif; ?>
</form>
<?php endif; ?>

<?php if ($kartyak): ?>
<div class="card scroll"><table>
<tr><th>Kártya-ID</th><?= $van_nev ? '<th>Név</th>' : '' ?><th class="num">Egyenleg (kassza)</th><th class="num">Napló szerint</th><th>Állapot</th>
<th>Utolsó mozgás</th><th class="num">Mozgások</th></tr>
<?php foreach ($kartyak as $k): $all = pa_kartya_allapot($k, $ig); ?>
<tr<?= (int)$k['ervenyes'] === 0 && $k['ervenyes'] !== null ? ' class="muted"' : '' ?>>
  <td class="mono"><?= (int)$k['kartya_id'] ?></td>
  <?php if ($van_nev): ?><td><?= h(pa_nev_mutat($k['nev_titkos'], $id, (int)$k['kartya_id'], $nmod)) ?></td><?php endif; ?>
  <td class="num"><?= $k['egyenleg'] !== null ? h(number_format((float)$k['egyenleg'], 0, ',', ' ')) : '–' ?></td>
  <td class="num"><?= $k['naplo_egyenleg'] !== null ? h(number_format((float)$k['naplo_egyenleg'], 0, ',', ' ')) : '–' ?></td>
  <td class="<?= $all === 'ok' ? 'ok' : ($all === 'eltér' ? 'bad' : 'muted') ?>"><?= h($all) ?></td>
  <td><?= h($k['utolso_mozgas'] ?? '–') ?></td>
  <td class="num"><?= (int)$k['mozgas'] ?></td>
</tr>
<?php endforeach; ?>
</table></div>
<?php endif; ?>

<?php if ($mozgasok): ?>
<h2>Legutóbbi kártyamozgások</h2>
<div class="card scroll"><table>
<?php $nevek_map = [];
foreach ($kartyak as $k) { $nevek_map[(int)$k['kartya_id']] = $k['nev_titkos']; } ?>
<tr><th>Idő</th><th>Kártya-ID</th><?= $van_nev ? '<th>Név</th>' : '' ?><th>Mozgás</th><th class="num">Összeg</th><th class="num">Utána</th></tr>
<?php foreach ($mozgasok as $mz): ?>
<tr>
  <td><?= h($mz['ido'] ?? '–') ?></td>
  <td class="mono"><?= (int)$mz['kartya_id'] ?></td>
  <?php if ($van_nev): ?><td><?= h(pa_nev_mutat($nevek_map[(int)$mz['kartya_id']] ?? null, $id, (int)$mz['kartya_id'], $nmod)) ?></td><?php endif; ?>
  <td><?= h(PA_KTIPUS[$mz['tipus']] ?? $mz['tipus']) ?></td>
  <td class="num"><?= h(number_format((float)$mz['osszeg'], 0, ',', ' ')) ?></td>
  <td class="num"><?= h(number_format((float)$mz['elotte'] + (float)$mz['osszeg'], 0, ',', ' ')) ?></td>
</tr>
<?php endforeach; ?>
</table></div>
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
