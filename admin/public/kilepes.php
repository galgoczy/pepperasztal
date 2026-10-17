<?php
declare(strict_types=1);
require __DIR__ . '/lib/app.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    pa_check_csrf();
    pa_logout();
}
header('Location: /');
