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

    // Ki lephet be: nev => Google e-mail-cim. Belepes Google-fiokkal vagy
    // passkey-jel; jelszo nincs. Aki innen kikerul, az a passkey-eivel sem
    // lep be tobbe.
    'admin_users' => [
        // 'gergely' => 'valaki@gmail.com',
    ],

    // Google-belepes (opcionalis). Google Cloud Console -> APIs & Services
    // -> Credentials -> OAuth client ID (Web application). Engedelyezett
    // atiranyitasi cim: https://pepperadmin.zentopia.io/google.php
    'google' => [
        'client_id' => '',
        'client_secret' => '',
    ],

    // Csak az elso passkey felvetelehez, ha Google-belepes nincs: legalabb
    // 20 veletlen karakter. A /elso-passkey.php oldalon a felhasznalonevvel
    // egyutt kell megadni. Ha mar van passkey-d, TOROLD ezt a sort.
    // 'setup_code' => '',
];
