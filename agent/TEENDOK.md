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

- **Szentkirályi átállítása az új verzióra (2026-10-17.5):** fájlcsere,
  `setup_users.py letrehoz` (szűkíti a `PEPPER_OLVAS`-t), `[felho]` az
  ini-be, `install_jelentes.bat`, újra az `install_backup.bat` (napközbeni
  mentés). Lépések: README, 7. pont.
- **RSR bekötése tesztre:** README, 7. pont.
- **Admin-belépés:** `admin_users` → `'nev' => 'gmail-cím'`, Google OAuth
  kliens a konfigurációba, utána passkey felvétele (`admin/README.md`, 3.
  pont).
- **`kiadas_kulcs.txt` a gépekre:** a kulcs kész, és a CI már aláírt kiadást
  készít. A fájlt minden gépre egyszer kézzel kell felmásolni (a frissítés
  sosem írja felül).

## Később

- **Majdnem élő frissítés a dashboardon** (a végén): a felhasználó pár
  másodperces frissítést lásson. Az ügynök állandóan futó folyamat legyen,
  percenkénti őrfeladattal (a Feladatütemező percnél sűrűbben nem indít), és
  változó ütemben jelentsen: nyitvatartásban 3–5 mp, éjjel 30–60 mp. A
  `KARTYANAPLO` ID-tartományos lekérdezése elhanyagolható terhelés. A
  Hostinger kéréskorlátait előtte meg kell nézni.
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
- **A NovoHost saját mentése** (`NH_AutoBackupService.exe`, `data\Backup`,
  utoljára 2025-09-06): mi van benne, fut-e még.
- **Ügynökszabály:** csak feltöltős (1-es típusú) kártyára hajt végre
  parancsot. A személyzeti kártyák és a limitek kimaradnak.

## Eldöntve (nem csinálunk)

- Tűzfal-szűkítés a 3050-es portra: a NovoHostnak saját kommunikációs igénye
  van.
- Hitelkeret: 2017 óta nincs használatban.
- Visszaállítási próba az éles gépen: csak külön teszt gépen.
