<?php
/** Esemenynaplo: az utolso 300 admin-muvelet. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$user = pa_require_login();
$rows = pa_db()->query('SELECT * FROM naplo ORDER BY id DESC LIMIT 300')->fetchAll();
pa_page_start('Napló', $user);
?>
<h1>Eseménynapló</h1>
<p class="sub">Belépések, tokenek, frissítések – az utolsó 300 esemény.</p>
<div class="card scroll"><table>
<tr><th>Idő</th><th>Ki</th><th>Mit</th><th>Részlet</th></tr>
<?php foreach ($rows as $r): ?>
<tr><td class="mono"><?= h($r['ido']) ?></td><td><?= h($r['ki']) ?></td>
    <td class="<?= $r['mit'] === 'belepes_hiba' ? 'bad' : '' ?>"><?= h($r['mit']) ?></td><td class="mono"><?= h($r['reszlet']) ?></td></tr>
<?php endforeach; ?>
</table></div>
<?php
pa_page_end();
