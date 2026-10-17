<?php
/**
 * Allapot JSON-ban - a deploy utani ellenorzes es a monitorozas hasznalja.
 * Titkot nem ad ki: csak verzio, build (commit), PHP-verzio, es hogy a
 * konfiguracio megvan-e, illetve az adatbazis elerheto-e.
 */

declare(strict_types=1);
require __DIR__ . '/lib/bootstrap.php';

pa_security_headers();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$st = pa_status();
http_response_code($st['ok'] ? 200 : 503);
echo json_encode($st, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), "\n";
