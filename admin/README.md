# Pepper Admin – pepperadmin.zentopia.io

A POS gépek ügynökeinek felhős oldala a Hostingeren (PHP + MySQL). Az
`admin/public/` mappa tartalma kerül fel az aldomainre. A GitHub Action
(`.github/workflows/deploy-admin.yml`) tölti fel FTP-n, minden `admin/` vagy
`agent/` változásnál, és ugyanez az Action készíti el az aláírt
ügynök-kiadást is.

## Mit tud

- **Helyszínek:** életjel percenként, ügynökverzió, adatbázis-elérés, az
  éjszakai és a napközbeni mentés állapota, a visszaállítási pontok listája.
  Az oldal 30 másodpercenként magától frissül.
- **Tokenek:** helyszínenként egy token. Felvételkor és cserekor egyszer
  látszik, a szerveren csak a hash-e marad meg. Egy gombbal cserélhető vagy
  visszavonható.
- **Ügynök-frissítés:** az elérhető aláírt kiadást helyszínenként (vagy egy
  gombbal mindenhol) ki lehet jelölni. A gép a következő jelentésnél
  (kb. 1 perc) letölti, ellenőrzi és telepíti.
- **Eseménynapló:** belépések, sikertelen belépések, token- és
  frissítési műveletek.
- **Visszaállítás innen szándékosan nem indítható**, és a gépnek parancsot
  sem küldünk. A kommunikáció egyirányú: a gép jelent, a felhő válaszol.

## Beállítás (egyszer)

### 1. GitHub-titkok

GitHub → a repó → Settings → Secrets and variables → Actions:

| Név | Mire |
|---|---|
| `FTP_SERVER`, `FTP_USERNAME`, `FTP_PASSWORD` | feltöltés (kész) |
| `AGENT_SIGNING_KEY` | az ügynök-kiadások **privát** aláíró kulcsa (lásd lent) |

### 2. Konfiguráció a szerveren (kész)

`pepperadmin-config.php` a webmappa fölött (1–4 szinttel feljebb), a
`config.example.php` mintájára. Ide kerül az adatbázis és a belépés.

### 3. Belépés: Google-fiók és passkey

Jelszavas belépés nincs. A konfigurációban (`config.example.php` minta):

```php
'admin_users' => ['gergely' => 'valaki@gmail.com'],
```

**Google-belépés** (egyszer, kb. 5 perc):

1. [Google Cloud Console](https://console.cloud.google.com/) → új projekt
   (pl. „Pepper Admin”).
2. *APIs & Services → OAuth consent screen*: External, alkalmazásnév, a
   saját e-mail-címed. Hatókör nem kell (csak `openid email`). Utána
   *Publish app* – ehhez ennyi hatókörrel nem kell Google-ellenőrzés.
3. *Credentials → Create credentials → OAuth client ID* → Web application.
   *Authorized redirect URIs*: `https://pepperadmin.zentopia.io/google.php`
4. A kapott Client ID és Client secret a konfiguráció `google` részébe kerül.
   A secret csak a szerveren legyen, chatbe és gitbe ne.

**Passkey:** belépés után a *Passkeyek* oldalon vehetsz fel egyet minden
eszközödhöz (telefon, laptop). Érdemes legalább egyet felvenni, hogy a
Google-belépés kiesése esetén is be tudj lépni.

**Első passkey Google nélkül:** tegyél a konfigurációba egy legalább 20
karakteres `setup_code`-ot, és a `/elso-passkey.php` oldalon a
felhasználónévvel együtt add meg. Utána a sort töröld; amíg ott van, a
kezdőoldal figyelmeztet.

### 4. Az aláíró kulcs – enélkül nincs távoli frissítés

A saját gépeden (például Git Bash-ben), egyszer:

```
openssl genrsa -out pepper_agent_priv.pem 3072
openssl rsa -in pepper_agent_priv.pem -noout -modulus
```

1. A `pepper_agent_priv.pem` **teljes tartalmát** másold az
   `AGENT_SIGNING_KEY` GitHub-secretbe, a fájlt pedig tedd biztonságos
   helyre (jelszókezelő).
2. A második parancs `Modulus=` utáni hexa része a **publikus** kulcs. Ezt
   nyugodtan megoszthatod: írd az `agent/kiadas_kulcs.txt` `n = ` sorába,
   vagy küldd el, és beírom.
3. Az `agent/kiadas_kulcs.txt` fájlnak a POS gépeken is ott kell lennie. A
   távoli frissítés ezt sosem írja felül, ezért **első alkalommal kézzel**
   kell odamásolni.

A CI minden kiadásnál ellenőrzi, hogy a secret és az `n` egyezik-e. Ha
nem, kiadás nem készül, és a hiba látszik az Action naplójában.

## Biztonság

- **A privát kulcs csak a GitHub-secretben van**, a szerveren soha. A szerver
  feltörésével sem lehet hamis kiadást csempészni a gépekre.
- **A gépek ellenőriznek telepítés előtt:**
  - az RSA-aláírást, a saját helyi publikus kulcsukkal;
  - hogy a verzió újabb-e (régebbire nem lépnek vissza);
  - hogy a csomag csak engedélyezett nevű fájlokat tartalmaz;
  - és hogy nem írja felül a `frissito.py`-t, a kulcsot vagy az ini-t.
- **A tokenek** csak hash-ként vannak az adatbázisban. A jelentésben küldött
  helyszín-kulcsnak egyeznie kell a tokenével.
- **Belépés:** Google (OpenID Connect, PKCE, state és nonce) vagy passkey
  (WebAuthn, mindig ujjlenyomat/arc/PIN-ellenőrzéssel, aláírás- és
  számlálóellenőrzéssel). A passkeyekből a szerveren csak a nyilvános kulcs
  van. Biztonságos session-süti, CSRF-védelem, IP-nként legfeljebb 5
  sikertelen belépés 15 percenként, 8 óra tétlenség után kilépés.
- **A webről nem érhető el:** a konfiguráció, a `lib/` és a `kiadasok/` mappa.
- **A jelentésben nincs üzleti vagy személyes adat:** se név, se
  kártyakód, se egyenleg, se nyugta.

## Oldalak

| Cím | Mi |
|---|---|
| `/` | belépés, majd a helyszínek áttekintése, új helyszín, frissítés mindenhol |
| `/helyszin.php?id=…` | egy helyszín részletei, célverzió, token, nyers jelentés |
| `/naplo.php` | eseménynapló |
| `/passkey.php` | saját passkeyek: felvétel, törlés |
| `/google.php` | Google-belépés (indulás és visszatérés) |
| `/elso-passkey.php` | első passkey beállító kóddal (csak ha van `setup_code`) |
| `/api/passkey.php` | passkey-műveletek az oldalak JavaScriptjének |
| `/allapot.php`, `/health.php` | telepítési állapot (titok nélkül) |
| `/api/jelentes.php` | a gépek percenkénti jelentése (token) |
| `/api/frissites.php` | aláírt kiadás letöltése (token, csak kijelölt verzió) |
