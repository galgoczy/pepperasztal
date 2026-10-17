# Pepper Admin – pepperadmin.zentopia.io

A POS gépek ügynökeinek felhős oldala a Hostingeren: PHP + MySQL. Az
`admin/public/` mappa tartalma kerül fel az aldomainre, a GitHub Action
(`.github/workflows/deploy-admin.yml`) tölti fel FTP-n.

Jelenleg csak egy állapotoldal (`/` és `/health.php`): verzió, a feltöltött
commit, a PHP-verzió, és hogy megvan-e a konfiguráció és működik-e az
adatbázis. Adatot még nem mutat, ezért belépés sem kell hozzá. A gépek
életjele és a mentések állapota a következő lépés, belépés mögött.

## Beállítás (egyszer)

### 1. GitHub-titkok

GitHub → a repó → Settings → Secrets and variables → Actions:

| Típus | Név | Érték |
|---|---|---|
| Secret | `FTP_SERVER` | az FTP-szerver (hPanel → Fájlok → FTP-fiókok) |
| Secret | `FTP_USERNAME` | a pepperadmin FTP-fiók felhasználóneve |
| Secret | `FTP_PASSWORD` | az FTP-fiók jelszava |
| Variable (opcionális) | `FTP_DIR` | a célmappa az FTP-fiók gyökeréhez képest; alap: `./` |
| Variable (opcionális) | `ADMIN_URL` | alap: `https://pepperadmin.zentopia.io` |

A titkok sehol nem jelennek meg: se a repóban, se a futási naplóban.

**`FTP_DIR`:** ha az FTP-fiókot az aldomainhez hoztad létre, a gyökere
általában maga az aldomain webmappája, és az alapérték (`./`) jó. Ha a
feltöltés lefut, de az ellenőrző lépés szerint nem az új verzió fut, rossz a
célmappa. Ilyenkor állítsd be például így: `public_html/`.

### 2. Konfiguráció a szerveren

A `config.example.php` mintája alapján hozd létre a hPanel
Fájlkezelőjében, az alábbi két hely közül az elsőre, ahová írni tudsz:

1. **a webmappa fölé**, `pepperadmin-config.php` néven (ajánlott: így a
   webről semmilyen módon nem érhető el);
2. **a webmappába**, `config.php` néven (a `.htaccess` tiltja a letöltését,
   és PHP-ként amúgy sem adna ki tartalmat).

Ebbe kerül az adatbázis neve, felhasználója és jelszava. A deploy ezt a
fájlt soha nem írja felül és nem törli. **A jelszót ne küldd el chatben, és
ne tedd a gitbe.**

### 3. Ellenőrzés

Nyisd meg: <https://pepperadmin.zentopia.io/>. Mind az öt sor zöld legyen. A
„Build" a GitHubon látható commit első 7 karaktere.

## Biztonság

- **HTTPS kötelező**: a `.htaccess` átirányít.
- **Nem tölthetők le közvetlenül**: a `config*.php`, a rejtett fájlok és a
  deploy állapotfájlja; a `lib/` mappa csak PHP-ból érhető el.
- **Az állapotoldal titkot nem ad ki**: adatbázis-hibánál csak annyit ír ki,
  hogy „hiba"; a részletek a szerver hibanaplójába mennek.
- **Keresők nem indexelik**: van `robots.txt` és `noindex` fejléc.
- **A Vercel-deploy kizárja az `admin/` mappát** (`.vercelignore`), így a
  PHP-fájlok nem jelennek meg a nyilvános appban.
