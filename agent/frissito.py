# -*- coding: utf-8 -*-
"""
frissito.py - alairt ugynok-csomag telepitese a Pepper Adminbol.

EZ A FAJL SOSEM FRISSUL TAVOLROL, es szandekosan csak a standard
konyvtarat hasznalja (nem importal a frissitheto fajlokbol). Ha egy
kiadas elrontana a tobbi fajlt, ez akkor is ep marad, es a kovetkezo
(javitott) kiadast telepiteni tudja. Csak kezzel csereld.

BIZTONSAG - mit ellenoriz telepites elott:
  1. Van-e helyi publikus kulcs (kiadas_kulcs.txt). Ha nincs: kikapcsolva.
  2. A celverzio UJABB-e a mostaninal (visszaleptetes tiltva - egy feltort
     admin egy regi, hibas alairt verziot sem tud visszakuldeni).
  3. A csomag sha256-ja egyezik a manifesttel ES az RSA-alairas (SHA-256,
     PKCS#1 v1.5) ervenyes a helyi kulccsal. A privat kulcs csak a GitHub
     secretben van, a szerveren nincs - a szerver feltorese sem eleg.
  4. A zip csak engedelyezett nevu, mappa nelkuli fajlokat tartalmaz, es
     nem irhatja felul ezt a fajlt, a kulcsot vagy az ini-t.
  5. A csomag common.py-janak verzioja pontosan a celverzio.
A regi fajlok az elozo\<verzio>\ mappaba kerulnek - kezi visszaallitashoz.
"""

import base64
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import ssl
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KULCS = os.path.join(HERE, "kiadas_kulcs.txt")
ALLAPOT = os.path.join(HERE, "frissites_allapot.json")
MAX_CSOMAG = 5 * 1024 * 1024
ENGEDETT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*\.(py|bat|md|example|pem)$")
TILTOTT = {"frissito.py", "kiadas_kulcs.txt", "pepper_agent.ini"}
DIGESTINFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def ver_parts(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def load_key():
    """kiadas_kulcs.txt: 'n = <hex modulus>' es 'e = 65537' sorok."""
    if not os.path.exists(KULCS):
        return None
    n = e = None
    with open(KULCS, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*([ne])\s*=\s*([0-9A-Fa-fx]+)\s*$", line)
            if m and m.group(1) == "n":
                n = int(m.group(2), 16)
            elif m and m.group(1) == "e":
                e = int(m.group(2), 16) if m.group(2).lower().startswith(
                    "0x") else int(m.group(2))
    if not n or not e or n.bit_length() < 2048:
        return None
    return n, e


def rsa_verify_sha256(data, sig, n, e):
    """RSA PKCS#1 v1.5 + SHA-256, tisztan stdlib-bol (pow). Atveve a
    novohost-cloud mukodo onfrissitesebol."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    h = hashlib.sha256(data).digest()
    ps = k - 3 - len(DIGESTINFO_SHA256) - len(h)
    if ps < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * ps + b"\x00" + DIGESTINFO_SHA256 + h
    return hmac.compare_digest(em, expected)


def _ssl_context():
    ctx = ssl.create_default_context()
    ca = os.path.join(HERE, "cacert.pem")
    if os.path.exists(ca):
        try:
            ctx.load_verify_locations(cafile=ca)
        except Exception:
            pass
    return ctx


def _get(url, token, limit):
    req = urllib.request.Request(url, headers={
        "X-Pepper-Token": token, "User-Agent": "PepperAgent-frissito"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError("tul nagy valasz")
    return body


def _save(eredmeny, verzio=None):
    d = {"ido": time.strftime("%Y-%m-%d %H:%M:%S"), "eredmeny": eredmeny}
    if verzio:
        d["verzio"] = verzio
    try:
        with open(ALLAPOT, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass
    return eredmeny


def frissit(url, token, info, jelenlegi):
    """info: a jelentes-valasz 'frissites' mezoje {verzio, sha256}.
    Visszaad: rovid, emberi eredmeny-szoveg (a dashboardon latszik)."""
    try:
        return _save(_frissit(url, token, info, jelenlegi), info.get("verzio"))
    except Exception as e:
        return _save("hiba: {0}".format(e)[:200], info.get("verzio"))


def _frissit(url, token, info, jelenlegi):
    kulcs = load_key()
    if not kulcs:
        return "kikapcsolva: nincs (ervenyes) kiadas_kulcs.txt"
    cel = str(info.get("verzio", ""))
    if not re.match(r"^[0-9][0-9.\-]{0,31}$", cel):
        return "elutasitva: hibas verzio"
    if ver_parts(cel) <= ver_parts(jelenlegi):
        return "elutasitva: {0} nem ujabb, mint {1}".format(cel, jelenlegi)

    base = "{0}/api/frissites.php?verzio={1}".format(url, cel)
    man = json.loads(_get(base + "&mit=manifest", token, 65536).decode("utf-8"))
    if man.get("verzio") != cel or man.get("sha256") != info.get("sha256"):
        return "elutasitva: a manifest nem egyezik a bejelentett verzioval"
    csomag = _get(base + "&mit=csomag", token, MAX_CSOMAG)
    if hashlib.sha256(csomag).hexdigest() != man["sha256"]:
        return "elutasitva: sha256 nem egyezik"
    try:
        sig = base64.b64decode(man.get("sig", ""), validate=True)
    except Exception:
        return "elutasitva: hibas alairas-formatum"
    if not rsa_verify_sha256(csomag, sig, kulcs[0], kulcs[1]):
        return "ELUTASITVA: AZ ALAIRAS ERVENYTELEN"

    fajlok = {}
    with zipfile.ZipFile(io.BytesIO(csomag)) as z:
        for zi in z.infolist():
            nev = zi.filename
            if nev.endswith("/"):
                continue
            if "/" in nev or "\\" in nev or ".." in nev \
                    or not ENGEDETT.match(nev) or nev in TILTOTT:
                return "elutasitva: nem engedelyezett fajl a csomagban: " + nev
            fajlok[nev] = z.read(zi)
    common = fajlok.get("common.py", b"").decode("utf-8", "replace")
    if 'AGENT_VERSION = "{0}"'.format(cel) not in common:
        return "elutasitva: a csomag verzioja nem {0}".format(cel)

    # Regi fajlok mentese, majd csere fajlonkent (tmp + os.replace).
    elozo = os.path.join(HERE, "elozo", re.sub(r"[^0-9.\-]", "_", jelenlegi))
    if not os.path.isdir(elozo):
        os.makedirs(elozo)
    for nev in fajlok:
        p = os.path.join(HERE, nev)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(elozo, nev))
    kesz = []
    try:
        for nev, tartalom in sorted(fajlok.items()):
            p = os.path.join(HERE, nev)
            tmp = p + ".uj"
            with open(tmp, "wb") as f:
                f.write(tartalom)
            os.replace(tmp, p)
            kesz.append(nev)
    except OSError as e:
        # Felbemaradt csere: ami mar kicserelodott, azt visszaallitjuk.
        for nev in kesz:
            regi = os.path.join(elozo, nev)
            if os.path.exists(regi):
                shutil.copy2(regi, os.path.join(HERE, nev))
        return "hiba a csere kozben, visszaallitva: {0}".format(e)
    return "frissitve: {0} -> {1} ({2} fajl)".format(jelenlegi, cel, len(kesz))
