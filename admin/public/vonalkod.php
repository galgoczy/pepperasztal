<?php
/**
 * Vonalkod a telefon kijelzojen. A kartyakod a gep pillanatkepebol jon
 * (titkositva tarolva), vagy kezzel irhato be; minden megjelenites naplozva.
 */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';
require __DIR__ . '/lib/kartyak.php';

$user = pa_require_login();
$db = pa_db();
$nmod = pa_nev_mod();

$valasztott = (string)($_GET['k'] ?? '');
$kod = null;
$hiba = null;
if (preg_match('/^(\d+):(\d+)$/', $valasztott, $m)) {
    $hid = (int)$m[1];
    $kid = (int)$m[2];
    $st = $db->prepare('SELECT k.kod_titkos, h.kulcs FROM kartya k JOIN helyszin h ON h.id = k.helyszin_id
                        WHERE k.helyszin_id = ? AND k.kartya_id = ?');
    $st->execute([$hid, $kid]);
    $r = $st->fetch();
    if (!$r || $r['kod_titkos'] === null) {
        $hiba = 'Ehhez a kártyához nincs tárolt kód.';
    } else {
        $kod = pa_visszafejt($r['kod_titkos'], pa_kod_cel($hid, $kid));
        if ($kod === null) {
            $hiba = 'A kód nem fejthető vissza (adat_kulcs?).';
        } else {
            pa_audit($user, 'kartyakod_mutatva', $r['kulcs'] . ' #' . $kid);
        }
    }
}

$kartyak = $db->query('SELECT k.helyszin_id, k.kartya_id, k.nev_titkos, h.nev AS hely FROM kartya k
                       JOIN helyszin h ON h.id = k.helyszin_id
                       WHERE k.kod_titkos IS NOT NULL ORDER BY h.nev, k.kartya_id')->fetchAll();

pa_page_start('Vonalkód', $user);
?>
<style>
  .vk { background: #fff; padding: 16px 8px 8px; margin: 12px -8px; border-radius: 6px; }
  .vk-cim { color: #000; margin: 0 0 8px; font-family: monospace; font-size: 15px; }
  .vk-kep svg { display: block; width: 100%; height: 120px; }
</style>
<h1>Vonalkód</h1>
<?php if ($kartyak): ?>
<form method="get" class="row">
  <select name="k" required>
    <option value="">Kártya…</option>
    <?php foreach ($kartyak as $k): $ert = (int)$k['helyszin_id'] . ':' . (int)$k['kartya_id']; ?>
    <option value="<?= h($ert) ?>"<?= $ert === $valasztott ? ' selected' : '' ?>><?= h($k['hely']) ?> · <?= (int)$k['kartya_id'] ?><?=
      $k['nev_titkos'] !== null ? ' · ' . h(pa_nev_mutat($k['nev_titkos'], (int)$k['helyszin_id'], (int)$k['kartya_id'], $nmod)) : '' ?></option>
    <?php endforeach; ?>
  </select>
  <button class="btn primary">Mutasd</button>
</form>
<p class="muted">A megjelenítés bekerül az eseménynaplóba. A nevek a helyszín oldalán beállított módon látszanak.</p>
<?php else: ?>
<p class="muted">Még nincs tárolt kártyakód (ügynök 2026-10-19.9 vagy újabb kell, és a következő pillanatkép).</p>
<?php endif; ?>
<?php if ($hiba): ?><p class="bad"><?= h($hiba) ?></p><?php endif; ?>
<p class="muted">Kézzel is beírhatod (pl. <code>;10120170103?</code>); a kézzel beírt kód csak ezen a telefonon marad.
Telefonon: fényerő maximumra.</p>
<input type="text" id="kod" autocomplete="off" autocapitalize="off" spellcheck="false"
       placeholder=";10120170103?" style="width:100%;font-family:monospace;font-size:18px"<?=
       $kod !== null ? ' value="' . h($kod) . '" data-szerver="1"' : '' ?>>
<div id="kodok"></div>
<script src="/vonalkod.js"></script>
<?php
pa_page_end();
