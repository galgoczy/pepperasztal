<?php
/**
 * Pepper Admin - konfiguracio MINTA.
 *
 * NE toltsd ki itt, es soha ne tedd a gitbe. A szerveren hozd letre a
 * hPanel Fajlkezelojeben, ezek kozul az elso helyre, ahova tudsz irni:
 *
 *   1. a webgyoker FELETT:  pepperadmin-config.php   (ajanlott)
 *   2. a webgyokerben:      config.php
 *
 * A deploy egyiket sem irja felul.
 */

return [
    // hPanel -> Adatbazisok -> MySQL adatbazisok
    'db_host' => 'localhost',
    'db_name' => 'u000000000_pepperadmin',
    'db_user' => 'u000000000_pepperadmin',
    'db_pass' => 'IDE_A_JELSZO',

    // Belepes az adminba. A hash-t a /jelszo.php oldal kesziti (amig nincs
    // egy felhasznalo sem, belepes nelkul is elerheto).
    'admin_users' => [
        // 'gergely' => '$2y$10$...',
    ],
];
