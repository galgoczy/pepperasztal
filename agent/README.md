# Pepper House – helyi ügynök (POS gép)

Ezek a scriptek a NovoHost2 POS gépein futnak, az InterBase adatbázis mellett.
Ez a 0. fázis: **mentés, korlátozott adatbázis-felhasználók és felderítés.**
Írás a POS adatbázisba ebben a fázisban **nincs**.

| Fájl | Mit csinál | Ír az adatbázisba? |
|---|---|---|
| `backup.py` | napi `gbak` mentés manifesttel, rotáció; `--proba`: ellenőrzés egy **másik** gépen | nem |
| `install_backup.bat` | a napi mentés ütemezett feladatként, SYSTEM fiókkal | nem |
| `setup_users.py` | `PEPPER_OLVAS` és `PEPPER_VIP` felhasználó és a jogaik | csak jogosultságot (GRANT) |
| `felderites.py` | csak olvasó felmérés a VIP-app tervezéséhez | nem |
| `common.py` | közös isql/ini/DPAPI réteg | – |

Python 3.4-től működik (XP-s gépek is), csak a standard könyvtárat használja.
Az első éles felderítés (Szentkirályi) szerint a szerver **InterBase 7.5**
(ODS 11.2, dialektus 3) – nem IB6, ahogy korábban feltételeztük. A
scriptek mindkettőn működnek.
Python adatbázis-driver **tilos**: a `firebirdsql` egyszer megfektette az éles
szervert, ezért minden az `isql.exe`-n, `gbak.exe`-n, `gsec.exe`-n keresztül megy.

---

## 1. Telepítés

1. Másold az `agent` mappa tartalmát a `C:\PepperApp\` mappába. Minden itt
   él: scriptek, ini, naplók, és a mentések a `C:\PepperApp\backup` alatt.
   **Ne a `Program Files` alá:** a nem emelt jogú írás oda a VirtualStore-ba
   kerül, és a SYSTEM-ként futó feladat nem látja.

2. Szűkítsd a mappa jogait, hogy csak a Rendszergazdák és a SYSTEM érje el
   (a jelszavak miatt). Rendszergazdai parancssorban:

   ```
   icacls C:\PepperApp /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F
   ```
   A SID-ek (`S-1-5-32-544` = Rendszergazdák, `S-1-5-18` = SYSTEM) magyar
   Windows-on is működnek, ahol a csoportnevek lefordítva szerepelnek.
   XP-n `icacls` helyett `cacls` van.

3. `pepper_agent.ini.example` → `pepper_agent.ini`, töltsd ki a helyszínt.

4. A SYSDBA jelszó titkosítva kerüljön az ini-be:
   ```
   python setup_users.py titkosit
   ```
   A kiírt `password_dpapi = …` sort másold a `[sysdba]` szakaszba.
   A DPAPI-blob gépre szól: másik gépen használhatatlan.

## 2. Mentés – ez az első, minden más előtt

```
install_backup.bat                 (jobb klikk → Futtatás rendszergazdaként)
schtasks /Run /TN "PepperHouse-Mentes"
```

Két ütemezett feladat jön létre:

| Feladat | Mikor | Mit csinál |
|---|---|---|
| `PepperHouse-Mentes` | éjjel, alapból 04:15 | mindig ment; 7 napi + 4 heti marad meg |
| `PepperHouse-Mentes-Napkozbeni` | 06:00–16:00, kétóránként | csak ha az előző mentés óta volt új nyugta vagy kártyamozgás; a `napkozbeni` mappába megy, 48 óráig marad meg |

A napközbeni mentés így „aktív napon" fut: zárva tartott napon kimarad, és
nem keletkezik felesleges mentés. Két mentés soha nem fut egyszerre.

A `mentes_log.txt` kiírja az adatbázis, a `.gbk` és az archívum méretét. A
`mentes_allapot.json` mindig mutatja az utolsó sikeres mentést és a meglévő
mentéseket.

Minden archívumban a `.gbk` mellett egy **manifest** is van: a kártyák száma,
az utolsó naplósor- és nyugta-azonosító a mentés pillanatában. Ebből
bizonyítható később, hogy a mentés **teljes**, nem csak olvasható.

- **Ugyanazon a gépen** marad, a `C:\PepperApp\backup` alatt (7 napi + 4
  heti; az ini-ben növelhető). Ez véd a hibás írás és a sérült adatbázis
  ellen, de **nem véd** a lemezhiba, a lopás és a zsarolóvírus ellen: ezek az
  adatbázist és a mentést együtt viszik. Ezért a `masolat_mappa`, később pedig
  a dashboardra titkosítva feltöltött másolat.
- **Mire jó és mire nem:** katasztrófánál (halott lemez, sérült adatbázis) a
  teljes visszaállítás a megoldás, **kézzel**. Egy VIP-egyenleghiba javítására
  viszont nem – az a pénztári forgalmat is visszavinné. Azt a naplókból kell
  újraszámolni.

Miért SYSDBA-val? InterBase 6-on a `gbak`-ot csak a SYSDBA vagy az adatbázis
tulajdonosa futtathatja; a korlátozott felhasználók nem tudnak menteni.

### A mentés ellenőrzése – egy MÁSIK gépen

Éles POS gépen **nem** állítunk vissza. A `backup.py --proba` meg is tagadja,
ha a gépen ott a NovoHost adatbázisa.

Kell hozzá egy teszt gép (irodai PC vagy virtuális gép), rajta InterBase 6
– ugyanaz a verzió, mint a kasszákon –, Python, és ez a mappa. Az ini-ben a
`[sysdba]` a **teszt gép** InterBase-ének jelszava, nem a kasszáé.

```
python backup.py --proba D:\mentesek\novohost_Knorr105_2026-10-17_041500.zip
```

Visszaállítja egy átmeneti fájlba, összeveti a manifesttel, majd törli.
Akkor jó a mentés, ha a visszaállított adatbázisban legalább annyi kártya,
naplósor és nyugta van, mint a manifestben. Új helyszín első mentésénél
kötelező, utána havonta egy-egy minta elég.

## 3. Korlátozott felhasználók

```
python setup_users.py jelszo        → a kiírt sorokat másold az ini-be
python setup_users.py terv          → mit fog csinálni (nem változtat semmit)
python setup_users.py letrehoz      → felhasználók + jogok + ellenőrzés
```

| Felhasználó | Jogok |
|---|---|
| `PEPPER_OLVAS` | `SELECT` minden táblára, kivéve a személyes adatot (`KARTYATULAJDONOS`) |
| `PEPPER_VIP` | `SELECT` + `INSERT`: `KARTYATORZS`, `KARTYANAPLO`; `SELECT`: `KARTYATIPUS`; `UPDATE` **csak** `AKT_KP`, `LIMIT_KP`, `AKT_FORG`, `KARTYA` |

Sehol nincs `DELETE`, és a `PEPPER_VIP` a nyugta- és ételtáblákat nem is látja.
A kártyabeszúráskor lefutó NovoHost-triggerek a szükséges jogot
**trigger-szinten** kapják (`GRANT … TO TRIGGER`), nem a felhasználó. Így a
`PEPPER_VIP` maga nem tud a `KARTYATULAJDONOS`-ba írni.

Az ellenőrzés (`python setup_users.py ellenoriz`, bármikor futtatható)
`WHERE ID = -1` feltételű utasításokkal próbálja ki, mit szabad és mit nem.
Ezek egyetlen sort sem érintenek, nem zárolnak, és nincs utánuk commit.

A 0 soros próba a **triggereket nem futtatja le**. Márpedig a NovoHost
triggerei (`KARTYATORZS_BU0`, `CHECK_54`) minden egyenleg-módosításnál
lefutnak, és nekik is kell jog. Ezt a valódi trigger-próba ellenőrzi:

```
python setup_users.py ellenoriz --triggerproba 610
```

Ez egy értékváltozás nélküli `UPDATE` a 610-es tesztkártyán (csak akkor
fut, ha a kártya neve „Minta"-val kezdődik), commit nélkül, visszagörgetve.

- **Mit véd:** a saját hibáinkat és egy feltört felhőt korlátozza. A
  legrosszabb eset „valaki egyenleget írt", nem „elveszett egy hónap forgalma".
- **Mit nem véd:** aki rendszergazda a POS gépen, mindent elér.
- A SYSDBA jelszavához **nem nyúlunk**, mert a NovoHost is azt használja.
- **Visszavonás:** `python setup_users.py visszavon --igen`. Csak azokat a
  trigger-jogokat veszi vissza, amelyeket a `letrehoz` adott hozzá
  (`setup_users_allapot.json`).
- Az IB6 a jelszónak csak az **első 8 karakterét** nézi. A `jelszo` lépés
  ezért pontosan 8 véletlen karaktert ad.

## 4. Felderítés

```
python felderites.py
```

Nyitvatartáson kívül futtasd. Alapból `PEPPER_OLVAS`-ként fut; ha az még
nincs, `--user sysdba`. A script minden utasítást ellenőriz, csak `SELECT`
mehet ki, és nincs `COMMIT`. `PEPPER_OLVAS`-ként maga az adatbázis is tiltja
az írást, ezért a felhasználók létrehozása után így futtasd.

A kimenet egy `felderites_<helyszín>_<dátum>.txt`. **Nincs benne név,
kártyakód vagy más személyes adat**, nyugodtan továbbítható. A válaszok,
amiket keresünk:

1. Tételesen látszik-e, mit vett a vendég VIP-pel? → pontgyűjtés tételre vagy összegre
2. Van-e részfizetés, és engedi-e a kassza a mínusz egyenleget? → app UX
3. Szabad-e a `29`-es EAN-prefix?
4. Van-e napi étlap a NovoHostban? (A korábbi menü-dump egy külön PostgreSQL rendszerből jött.)
5. Igaz-e a `LIMIT_KP − AKT_FORG = AKT_KP` invariáns?
6. Mit csinál a `LIMIT` / `LIMITALVA` / `KARTYAGYUJTO`?
7. Él-e még a 610-es tesztkártya?
8. Mely triggerek futnak le íráskor? → kell-e még jog a `setup_users.py`-ba
9. InterBase-verzió, ODS, dialektus, és ki kapcsolódik a 3050-es porthoz

## 5. A 3050-es port

A SYSDBA jelszó kiszivárgott és nem cserélhető, ezért az adatbázist csak az
érje el, akinek muszáj. **Vakon lezárni tilos:** több kasszás helyszínen a
többi kassza is ezen a porton éri el az adatbázist. A felderítés 0. szakasza
megmutatja, ki kapcsolódik ma. Tűzfalszabály csak ezek ismeretében készüljön,
és csak ezeket az IP-ket engedje.
