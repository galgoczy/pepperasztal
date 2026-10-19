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

- **Élő kártyamozgások, vásárolt tételek, gépterhelés (2026-10-19.5):**
  távoli frissítéssel megy fel. A gépterhelés-mérés Windows API-t használ,
  élesben még nem futott – az első jelentések után ellenőrizni.
- **Feltöltés / levonás az adminból (2026-10-19.6):** kész, csak
  Szentkirályin bekapcsolva (`[iras] be = igen`). Tesztkártya: Minta Géza
  (610). Éles használat előtt: aláírt utasítás (a kulcs ne a szerveren
  legyen), és kétlépcsős azonosítás a Google-, Hostinger- és GitHub-fiókon.
- **Tesztfelhasználó felvétele az adminból:** félretéve.
- **Gyorsabb utasítás-átvétel (élesítés előtt):** most az utasítás a
  percenkénti életjel válaszában megy le, ezért legfeljebb kb. 1 percet vár.
  Terv: a gyors figyelés nyitvatartásban 10 másodpercenként kérdezze meg a
  szervert, van-e utasítás. Csak ott, ahol `[iras] be = igen`.
- **A novohost-cloud `python/vip_test_write.py` nyílt SYSDBA-jelszót
  tartalmaz** – onnan törölni (a git-előzményben megmarad).

- **Feltöltős kártyák a felhőben (2026-10-18.1):** a `kartyak.py` csak
  olvasva küldi a `KARTYANAPLO` feltöltős sorait, az egyenlegeket, a neveket
  és a napi egyeztetést; az admin helyszín-oldalán látszik. Élesben:
  `adat_kulcs` a szerveri konfigurációba, célverzió `2026-10-18.1`, utána
  az előzmény ~1 óra alatt felmegy.

- **Szentkirályi:** átállítva, percenként jelent az adminnak (2026-10-17).
  Most erre az egy helyszínre koncentrálunk.
- **Admin-belépés:** `admin_users` → `'nev' => 'gmail-cím'`, Google OAuth
  kliens a konfigurációba, utána passkey felvétele (`admin/README.md`, 3.
  pont).
- **`kiadas_kulcs.txt` a gépekre:** a kulcs kész, és a CI már aláírt kiadást
  készít. A fájlt minden gépre egyszer kézzel kell felmásolni (a frissítés
  sosem írja felül).

## Később

- **További helyszínek: RSR és TTK** (itt lehet tesztelni). Félretéve, amíg
  Szentkirályi stabil. Lépések: README, 7. pont.

- **A meglévő kártyák mágneskártyák** (a `;…?` kódforma a mágnescsík
  2. sávja). A kódok titkosítva felmennek (2026-10-19.9), az admin
  Vonalkód oldala ebből rajzol. Vonalkóddal egyelőre csak a 610-es
  tesztkártyát használjuk. Ahol vonalkód-olvasó van, bármelyik kártya
  kódjából készült vonalkóddal lehet fizetni – a kódok megjelenítése ezért
  naplózott.
- **Kódforma (Szentkirályi, helyszíni ellenőrzés):** `;XXXÉÉÉÉHHNN?` –
  3 jegyű sorszám + egy dátum, amely egy adagon belül a legtöbb kártyán
  azonos. Minta Géza (610): `;00000000001?`. Saját kiosztásnál ettől jól
  elkülönülő tartomány kell (pl. saját „dátum”-blokk), hogy ne ütközzön a
  NovoHost-kártyákkal. A dátumok múltbeliek (valószínűleg a kártyaadag
  gyártási/kódolási napja). TTK-ban ugyanez a forma (2021–2024-es adagok).
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
- **Kártyanyitás és technikai név** (a NovoHost egy helyszínen belül nem
  enged két azonos `NEV`-et, a személyzeti kártyákkal együtt sem):
  - a helyszín gépe a saját adatbázisa összes nevét nézi, és egyedi nevet
    választ („Tóth János”, „Tóth János 2”, …); ütközés a kis-/nagybetű
    és a szóköz eltérése is; a `NEV` `VARCHAR(40)` (Szentkirályin a
    leghosszabb név 16 karakter), ezért hosszú névnél az alapnevet vágjuk,
    hogy a sorszám beférjen; a `KARTYA` `VARCHAR(20)`, egy EAN-13 kód
    elválasztójelekkel (`;…?`, 15 karakter) is belefér;
  - verseny esetén a `VAN_MAR_ILYEN_NEV` hibára a következő sorszámmal
    újrapróbál;
  - visszajelzi a felhőnek: felhasználó → helyszín → kártya-ID + technikai
    név. Más kártyák nevét (személyzet, többi vendég) a felhő nem kapja meg;
  - ha a kasszán átnevezik a kártyát, a gép a következő szinkronnál
    jelenti az új nevet.

## Eldöntve (nem csinálunk)

- Tűzfal-szűkítés a 3050-es portra: a NovoHostnak saját kommunikációs igénye
  van.
- Hitelkeret: 2017 óta nincs használatban.
- Visszaállítási próba az éles gépen: csak külön teszt gépen.
