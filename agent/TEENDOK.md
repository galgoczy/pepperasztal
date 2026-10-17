# Teendők – helyi ügynök (POS gép)

Nyitott tételek, nagyjából fontossági sorrendben. A kész tételek kikerülnek.

## Kész – Szentkirályi (2026-10-17)

- Mentés manifesttel: 157 MB → 80,7 MB gbk → 13,9 MB zip, 8 mp.
- `PEPPER_OLVAS` és `PEPPER_VIP` létrehozva, 16/16 ellenőrzés zöld.
- Valódi trigger-próba a 610-es tesztkártyán: a `CHECK_54` és a
  `KARTYATORZS_BU0` jogai rendben, az egyenleg-`UPDATE` átmegy.
- Felderítés `PEPPER_OLVAS`-ként lefutott. Megállapítások:
  - Feltöltős kártyánál minden VIP-fizetéshez van `FK` naplósor pontosan
    azonos összeggel → a költés-értesítés a `KARTYANAPLO`-ra épül.
  - Napi egyeztetés: `AKT_KP` = utolsó naplósor `AKT + OSSZEG` (22/22).
  - Részfizetés: VIP + készpénz előfordul (10 eset, mind feltöltős kártya).
    Mínuszba soha nem ment egyetlen kártya sem.
  - A `2`-es termékkódok 3–4 jegyűek, 13 jegyű kóddal nem ütköznek.
  - A napi étlap nem a NovoHostban él.

## Folyamatban

- **A mentés ütemezett feladata:** ellenőrizni, hogy a `PepperHouse-Mentes`
  fel van-e telepítve, és a „Next Run Time" nem N/A.

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
- **Pontszabály a valódi kategóriákra** (`ETELTIP`, jóváhagyja a Pepper
  House). Javaslat:
  - 1 pont: Menü 1 (16), Menü 2 (17), Fitness menü (18)
  - 2 pont: Főétel (9), Egytálétel (8), Wok (27), Rántott (29), Halak (31);
    kérdéses: Főzelékek (6), Tészták (32), Napi frissen sültek (33)
  - 0 pont: minden más, különösen a VIP Töltés (36), Kiszállítás (35),
    Protokoll (24), Rendezvény (26), betétdíj, pohár, doboz
- **`PEPPER_OLVAS` szűkítése – a felhős rész előtt kötelező.** Ma 172 táblát
  lát, köztük személyes adatot is: `VEVOK`, `FOGLALAS`, `CIMEK`, `SZEMELYZET`,
  `KEZELO`, `TULAJDONOS`, `UTCAJEGYZEK`. Az ügynöknek ennyi kell:
  `KARTYATORZS`, `KARTYANAPLO`, `KARTYATIPUS`, `NYUGTAFEJ`, `NYUGTAFIZETES`,
  `NYUGTATETEL`, `ETELFAJ`, `ETELTIP` (a felderítéshez még `CIKKEK`,
  `GEPETLAP`, `ETLAPOK`, `KARTYAGYUJTO`). A `setup_users.py` tiltólista
  helyett engedélylistát kapjon, és vegye vissza a többit.
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
