# Teendők – helyi ügynök (POS gép)

Nyitott tételek, nagyjából fontossági sorrendben. A kész tételek kikerülnek.

## Folyamatban

- **Korlátozott felhasználók – Szentkirályi.** `setup_users.py letrehoz`, majd
  `ellenoriz --triggerproba 610`. Az első futás a `gsec` miatt megállt (semmi
  nem változott), a javítás után újra kell futtatni.
- **`CHECK_54` trigger-jog.** Nem biztos, hogy az InterBase enged jogot egy
  ellenőrző triggernek. A `--triggerproba 610` dönti el; ha hibát ad, más
  megoldás kell.

## Később

- **Napközbeni mentés: aktív napon 06:00 és 16:00 között 2 óránként.** Egy
  157 MB-os adatbázis mentése 8 mp volt, ez napközben sem terheli a kasszát.
  Amikor sorra kerül:
  - **Ütemezés:** az `install_backup.bat` napi feladata kapjon egy második,
    napközbeni feladatot (`/SC DAILY /ST 06:00 /RI 120 /DU 10:00`), vagy a
    meglévő éjszakai mellett ez legyen az alap.
  - **„Aktív nap":** ne a hét napjai alapján döntsünk, hanem a mentés
    maradjon ki, ha az előző mentés óta nincs új nyugta. A manifestben ott az
    utolsó nyugta-azonosító, ezt kell összevetni.
  - **Rotáció átalakítása – enélkül nem élesíthető.** Napi 6 mentésnél a
    mostani `napi_db = 7` alig több mint egy napot őrizne meg. Új szabály:
    az elmúlt 24–48 óra minden mentése marad, régebbről naponta csak az
    utolsó, és a hetiek, mint most.
  - **Méret:** a 14 MB-os archívummal ez napi kb. 85 MB, bőven elfér. Nagyobb
    helyszínen előbb mérni kell.
- **Vonalkód-teszt a régi USB-s olvasóval.** Telefon maximális fényerőn,
  először Jegyzettömbbe olvasva: beolvassa-e a kijelzőt, és helyesen
  érkeznek-e a `;` és `?` karakterek. Utána a NovoHost VIP-kártyás ablakában
  a 610-es tesztkártyával. Tesztoldal kérésre készül.
- **Az app vonalkód-képernyője:** fényerő maximumra, a képernyő ne aludjon
  el, fehér háttér. Ez natív appban megoldható, PWA-ban nem.
- **Pontszabály a valódi kategóriákra** (`ETELTIP`): a menü- és
  főétel-kategóriák listáját a Pepper House hagyja jóvá. A csomagolás és a
  betétdíj nem kap pontot.
- **`PEPPER_OLVAS` szűkítése** a most engedélyezett 172 tábláról arra a 6–8
  táblára, amire az ügynöknek valóban szüksége van.
- **A NovoHost saját mentése** (`NH_AutoBackupService.exe`, `data\Backup`,
  utoljára 2025-09-06): mi van benne, fut-e még.
- **Hostinger:** aldomain, PHP-verzió, üres MySQL-adatbázis külön
  felhasználóval. Első lépésként a gépek percenként jelentik az életjelüket
  és a mentés állapotát (`mentes_allapot.json`).
- **Ügynökszabály:** csak feltöltős (1-es típusú) kártyára hajt végre
  parancsot. A személyzeti kártyák és a limitek kimaradnak.

## Eldöntve (nem csinálunk)

- Tűzfal-szűkítés a 3050-es portra: a NovoHostnak saját kommunikációs igénye
  van.
- Hitelkeret: 2017 óta nincs használatban.
- Visszaállítási próba az éles gépen: csak külön teszt gépen.
