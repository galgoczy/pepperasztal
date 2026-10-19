<?php
/** Vonalkod-teszt a telefon kijelzojen. A kod csak a bongeszoben el. */

declare(strict_types=1);
require __DIR__ . '/lib/app.php';

$user = pa_require_login();

pa_page_start('Vonalkód-teszt', $user);
?>
<style>
  .vk { background: #fff; padding: 16px 8px 8px; margin: 12px -8px; border-radius: 6px; }
  .vk-cim { color: #000; margin: 0 0 8px; font-family: monospace; font-size: 15px; }
  .vk-kep svg { display: block; width: 100%; height: 120px; }
</style>
<h1>Vonalkód-teszt</h1>
<p class="muted">Írd be a kártya kódját, ahogy a NovoHost kártyatörzsében áll (pl. <code>;10120170103?</code>).
A kód csak ezen a telefonon marad, a szerverre nem megy fel. Telefonon: fényerő maximumra.</p>
<input type="text" id="kod" autocomplete="off" autocapitalize="off" spellcheck="false"
       placeholder=";10120170103?" style="width:100%;font-family:monospace;font-size:18px">
<div id="kodok"></div>
<script src="/vonalkod.js"></script>
<?php
pa_page_end();
