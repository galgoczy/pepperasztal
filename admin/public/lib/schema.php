<?php
/**
 * Adatbazis-sema. Az elso kereskor magatol letrejon (CREATE ... IF NOT
 * EXISTS), es a meta.sema_verzio alapjan kesobb bovitheto. MySQL-en es
 * (helyi teszthez) SQLite-on is fut.
 */

declare(strict_types=1);

const PA_SCHEMA_VERSION = 5;

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
    // 2: passkeyek (a nyilvanos kulcs PEM-ben, a kulcsazonosito base64url)
    $db->exec("CREATE TABLE IF NOT EXISTS passkey (
        id $pk,
        felhasznalo VARCHAR(64) NOT NULL,
        cred_id VARCHAR(191) NOT NULL UNIQUE,
        kulcs TEXT NOT NULL,
        alg INT NOT NULL,
        szamlalo BIGINT NOT NULL DEFAULT 0,
        nev VARCHAR(100) NOT NULL,
        letrehozva VARCHAR(19) NOT NULL,
        utoljara VARCHAR(19) NULL)$tail");
    // 3: feltoltos kartyak - egyenleg-pillanatkep es a KARTYANAPLO mozgasai
    // (nev es kartyakod nelkul; a kartya-ID a helyszin NovoHostjaban ervenyes)
    $db->exec("CREATE TABLE IF NOT EXISTS kartya (
        helyszin_id INT NOT NULL,
        kartya_id INT NOT NULL,
        egyenleg DECIMAL(14,2) NULL,
        egyenleg_ido VARCHAR(19) NULL,
        egyenleg_gen INT NULL,
        ervenyes SMALLINT NULL,
        naplo_egyenleg DECIMAL(14,2) NULL,
        utolso_naplo_id INT NULL,
        utolso_mozgas VARCHAR(19) NULL,
        PRIMARY KEY (helyszin_id, kartya_id))$tail");
    $db->exec("CREATE TABLE IF NOT EXISTS kartyamozgas (
        helyszin_id INT NOT NULL,
        naplo_id INT NOT NULL,
        kartya_id INT NOT NULL,
        tipus VARCHAR(4) NOT NULL,
        osszeg DECIMAL(14,2) NULL,
        elotte DECIMAL(14,2) NULL,
        ido VARCHAR(19) NULL,
        erkezett VARCHAR(19) NOT NULL,
        PRIMARY KEY (helyszin_id, naplo_id))$tail");
    $db->exec("CREATE TABLE IF NOT EXISTS helyszin_allapot (
        helyszin_id INT NOT NULL,
        k VARCHAR(32) NOT NULL,
        v MEDIUMTEXT NULL,
        ido VARCHAR(19) NOT NULL,
        PRIMARY KEY (helyszin_id, k))$tail");
    // 5: mit vett - a koltes (FK naplosor) nyugtajanak tetelei JSON-ban
    $db->exec("CREATE TABLE IF NOT EXISTS kartyavasarlas (
        helyszin_id INT NOT NULL,
        naplo_id INT NOT NULL,
        nyugta_id INT NOT NULL,
        kartya_id INT NOT NULL,
        ido VARCHAR(19) NULL,
        osszeg DECIMAL(14,2) NULL,
        vegertek DECIMAL(14,2) NULL,
        tetelek MEDIUMTEXT NULL,
        PRIMARY KEY (helyszin_id, naplo_id))$tail");
    // 4: a kartya neve titkositva (lib/titok.php)
    try {
        $db->exec('ALTER TABLE kartya ADD COLUMN nev_titkos TEXT NULL');
    } catch (Throwable $e) {
        // mar letezik
    }
    if ($sqlite) {
        $db->exec('CREATE INDEX IF NOT EXISTS ix_mozgas_kartya ON kartyamozgas (helyszin_id, kartya_id, naplo_id)');
    } else {
        try {
            $db->exec('CREATE INDEX ix_mozgas_kartya ON kartyamozgas (helyszin_id, kartya_id, naplo_id)');
        } catch (Throwable $e) {
            // mar letezik
        }
    }
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

/** Helyszinenkenti allapot (pl. naplo-kurzor, napi egyeztetes) - kulcs/ertek. */
function pa_hely_set(int $hid, string $k, string $v): void
{
    $db = pa_db();
    $up = $db->prepare('UPDATE helyszin_allapot SET v = ?, ido = ? WHERE helyszin_id = ? AND k = ?');
    $up->execute([$v, pa_now(), $hid, $k]);
    if ($up->rowCount() === 0) {
        $db->prepare('INSERT INTO helyszin_allapot (helyszin_id, k, v, ido) VALUES (?, ?, ?, ?)')
            ->execute([$hid, $k, $v, pa_now()]);
    }
}

function pa_hely_get(int $hid, string $k): ?array
{
    $st = pa_db()->prepare('SELECT v, ido FROM helyszin_allapot WHERE helyszin_id = ? AND k = ?');
    $st->execute([$hid, $k]);
    $r = $st->fetch();
    return $r ?: null;
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
