<?php
/**
 * Adatbazis-sema. Az elso kereskor magatol letrejon (CREATE ... IF NOT
 * EXISTS), es a meta.sema_verzio alapjan kesobb bovitheto. MySQL-en es
 * (helyi teszthez) SQLite-on is fut.
 */

declare(strict_types=1);

const PA_SCHEMA_VERSION = 1;

function pa_is_sqlite(): bool
{
    return pa_db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'sqlite';
}

function pa_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = pa_db();
    $sqlite = pa_is_sqlite();
    $pk = $sqlite ? 'INTEGER PRIMARY KEY AUTOINCREMENT' : 'INT AUTO_INCREMENT PRIMARY KEY';
    $tail = $sqlite ? '' : ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4';

    $db->exec("CREATE TABLE IF NOT EXISTS meta (
        k VARCHAR(64) PRIMARY KEY, v TEXT)$tail");
    $ver = (int)($db->query("SELECT v FROM meta WHERE k = 'sema_verzio'")->fetchColumn() ?: 0);
    if ($ver >= PA_SCHEMA_VERSION) {
        return;
    }

    $db->exec("CREATE TABLE IF NOT EXISTS helyszin (
        id $pk,
        kulcs VARCHAR(64) NOT NULL UNIQUE,
        nev VARCHAR(100) NOT NULL,
        token_hash CHAR(64) NULL UNIQUE,
        token_letrehozva VARCHAR(19) NULL,
        cel_verzio VARCHAR(32) NULL,
        letrehozva VARCHAR(19) NOT NULL)$tail");
    $db->exec("CREATE TABLE IF NOT EXISTS jelentes (
        helyszin_id INT PRIMARY KEY,
        ido VARCHAR(19) NOT NULL,
        ip VARCHAR(45) NULL,
        gep VARCHAR(100) NULL,
        agent_verzio VARCHAR(32) NULL,
        adat MEDIUMTEXT NULL)$tail");
    $db->exec("CREATE TABLE IF NOT EXISTS naplo (
        id $pk,
        ido VARCHAR(19) NOT NULL,
        ki VARCHAR(64) NOT NULL,
        mit VARCHAR(64) NOT NULL,
        reszlet TEXT NULL)$tail");
    $db->exec("CREATE TABLE IF NOT EXISTS login_proba (
        id $pk,
        ip VARCHAR(45) NOT NULL,
        ido VARCHAR(19) NOT NULL)$tail");
    if ($sqlite) {
        // MEDIUMTEXT -> sqlite-ban TEXT affinitas, rendben van.
        $db->exec('CREATE INDEX IF NOT EXISTS ix_login_ip ON login_proba (ip, ido)');
    } else {
        try {
            $db->exec('CREATE INDEX ix_login_ip ON login_proba (ip, ido)');
        } catch (Throwable $e) {
            // mar letezik
        }
    }

    $up = $db->prepare($sqlite
        ? "INSERT OR REPLACE INTO meta (k, v) VALUES ('sema_verzio', ?)"
        : "REPLACE INTO meta (k, v) VALUES ('sema_verzio', ?)");
    $up->execute([(string)PA_SCHEMA_VERSION]);
}

function pa_now(): string
{
    return date('Y-m-d H:i:s');
}

/** Esemenynaplo: ki, mit, mikor - minden admin-muvelet ide kerul. */
function pa_audit(string $ki, string $mit, string $reszlet = ''): void
{
    pa_db()->prepare('INSERT INTO naplo (ido, ki, mit, reszlet) VALUES (?, ?, ?, ?)')
        ->execute([pa_now(), $ki, $mit, mb_substr($reszlet, 0, 2000)]);
}
