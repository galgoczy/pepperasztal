# -*- coding: utf-8 -*-
"""
common.py - kozos reteg a Pepper House helyi ugynok scriptjeihez.

Mit ad:
  - a pepper_agent.ini beolvasasa (jelszavak DPAPI-val titkositva is)
  - isql.exe hivas helyesen: SET NAMES WIN1250 a CONNECT elott, cp1250
    be- es kimenet, konzolablak nelkul, normal alatti prioritassal
  - SET LIST ON kimenet parszolasa
  - a gsec / gbak / gstat hivasa ugy, hogy a SYSDBA jelszo NE a
    parancssorba keruljon (ISC_USER / ISC_PASSWORD kornyezeti valtozo)

Python 3.4-tol mukodik (XP-s POS gepek): nincs f-string, nincs
subprocess.run, nincs secrets modul.

A bevalt megoldasok forrasa a novohost-cloud repo (live_sales_sync.py,
vip_test_write.py); itt csak az ugynokhoz szukseges resz van, onalloan.
"""

import base64
import os
import re
import subprocess
import sys
import time

# Minden kiadasnal noveld - a scriptek indulaskor kiirjak, igy egy
# hibajelentesbol azonnal latszik, melyik verzio fut a gepen.
AGENT_VERSION = "2026-10-19.3"

HERE = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(HERE, "pepper_agent.ini")

# Az isql minden futas vegen kiir egy artalmatlan sort a stderr-re.
# Ha nem szurjuk ki, elfedi a valodi hibat - es forditva: ha mindent
# hibanak veszunk, ami a stderr-en van, minden futas "hibas".
BENIGN = "Use CONNECT or CREATE DATABASE to specify a database"

# Windows: ne villanjon fel konzolablak a penztargepen, es a kassza
# programja mindig elsobbseget kapjon. Mas rendszeren nincs hatasa.
_CREATE_NO_WINDOW = 0x08000000
_BELOW_NORMAL = 0x00004000


# ===========================================================================
# Konfiguracio
# ===========================================================================

class Config(object):
    """A pepper_agent.ini tartalma, alapertelmezesekkel."""

    def __init__(self):
        self.ib_bin = r"C:\Program Files (x86)\Borland\InterBase\bin"
        # A felhasznalokat tarolo biztonsagi adatbazis (IB 7.x: admin.ib,
        # IB6: isc4.gdb). Ures = az InterBase mappajaban keressuk.
        self.security_db = ""
        self.db_path = (r"C:\Program Files (x86)\novohost2\nhtouch"
                        r"\data\novohost.ib")
        self.helyszin = ""
        # felhasznalo-kulcs -> (nev, jelszo vagy None)
        self.users = {
            "sysdba": ["SYSDBA", None],
            "olvas": ["PEPPER_OLVAS", None],
            "vip": ["PEPPER_VIP", None],
        }
        self.backup = {
            "mappa": os.path.join(HERE, "backup"),
            "masolat_mappa": "",
            "napi_db": 7,
            "heti_db": 4,
            "napkozbeni_ora": 48,
            "sevenzip": "",
            "archiv_jelszo": None,
        }
        # A Pepper Admin (felho) eleresi adatai - jelentes.py
        self.felho = {"url": "", "token": None}
        # Feltoltos kartyak mozgasai a felhobe (kartyak.py). kezdet: ettol a
        # KARTYANAPLO.ID-tol kuld eloszor (0 = a teljes elozmeny).
        self.kartyak = {"kuldes": True, "kezdet": 0, "lap": 300, "nevek": True}
        self.loaded_from = None

    def security_db_path(self):
        if self.security_db:
            return self.security_db
        root = os.path.dirname(self.ib_bin.rstrip("\\/"))
        for name in ("admin.ib", "isc4.gdb", "security.fdb"):
            p = os.path.join(root, name)
            if os.path.exists(p):
                return p
        return ""

    def tool(self, name):
        return os.path.join(self.ib_bin, name)

    @property
    def isql(self):
        return self.tool("isql.exe" if os.name == "nt" else "isql")

    def user(self, key):
        return self.users[key][0]

    def password(self, key):
        pw = self.users[key][1]
        if not pw:
            raise ConfigError(
                "Nincs jelszo megadva a(z) [{0}] szakaszban a "
                "pepper_agent.ini-ben.".format(key))
        return pw


class ConfigError(Exception):
    pass


def _read_password(cfg, section, name="password"):
    """<name>_dpapi elsobbseget elvez a nyilt <name>-mel szemben."""
    enc = cfg.get(section, name + "_dpapi", fallback="").strip()
    if enc:
        try:
            return dpapi_unprotect(enc)
        except Exception as e:
            log("FIGYELEM: [{0}] {1}_dpapi visszafejtese nem sikerult "
                "({2}); a nyilt ertekre esem vissza, ha van.".format(
                    section, name, e))
    pw = cfg.get(section, name, fallback="").strip()
    return pw or None


def load_config(path=INI_PATH):
    import configparser
    c = Config()
    if not os.path.exists(path):
        return c
    cfg = configparser.ConfigParser()
    try:
        cfg.read(path, encoding="utf-8")
    except TypeError:
        cfg.read(path)
    c.loaded_from = path

    if cfg.has_section("interbase"):
        c.ib_bin = cfg.get("interbase", "bin", fallback=c.ib_bin).strip()
        c.db_path = cfg.get("interbase", "db_path", fallback=c.db_path).strip()
        c.security_db = cfg.get("interbase", "security_db",
                                fallback="").strip()
    if cfg.has_section("general"):
        c.helyszin = cfg.get("general", "helyszin", fallback="").strip()
    for key in c.users:
        if cfg.has_section(key):
            c.users[key][0] = cfg.get(key, "user",
                                      fallback=c.users[key][0]).strip().upper()
            c.users[key][1] = _read_password(cfg, key)
    if cfg.has_section("felho"):
        c.felho["url"] = cfg.get("felho", "url", fallback="").strip().rstrip("/")
        c.felho["token"] = _read_password(cfg, "felho", "token")
    if cfg.has_section("kartyak"):
        k = c.kartyak
        k["kuldes"] = cfg.get("kartyak", "kuldes", fallback="igen").strip().lower() \
            not in ("nem", "no", "false", "0", "off", "ki")
        k["nevek"] = cfg.get("kartyak", "nevek", fallback="igen").strip().lower() \
            not in ("nem", "no", "false", "0", "off", "ki")
        k["kezdet"] = cfg.getint("kartyak", "kezdet", fallback=0)
        k["lap"] = max(10, min(1000, cfg.getint("kartyak", "lap", fallback=300)))
    if cfg.has_section("backup"):
        b = c.backup
        b["mappa"] = cfg.get("backup", "mappa", fallback=b["mappa"]).strip()
        b["masolat_mappa"] = cfg.get("backup", "masolat_mappa",
                                     fallback="").strip()
        b["napi_db"] = cfg.getint("backup", "napi_db", fallback=b["napi_db"])
        b["heti_db"] = cfg.getint("backup", "heti_db", fallback=b["heti_db"])
        b["napkozbeni_ora"] = cfg.getint("backup", "napkozbeni_ora",
                                         fallback=b["napkozbeni_ora"])
        b["sevenzip"] = cfg.get("backup", "sevenzip", fallback="").strip()
        b["archiv_jelszo"] = _read_password(cfg, "backup")
    return c


# ===========================================================================
# DPAPI - gephez kotott jelszo-titkositas (Windows)
# ===========================================================================
#
# A titkositott blob CSAK azon a gepen fejtheto vissza, ahol keszult
# (LOCAL_MACHINE). Igy az ini-ben nincs olvashato jelszo, es masik gepre
# masolva hasznalhatatlan. Atveve a live_sales_sync.py-bol.

def _dpapi(protect, data):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    raw = base64.b64decode(data) if not protect else data.encode("utf-8")
    buf = ctypes.create_string_buffer(raw, len(raw))
    src = BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    LOCAL_MACHINE = 0x4
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    ok = fn(ctypes.byref(src), None, None, None, None,
            LOCAL_MACHINE, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI hiba (kod {0})".format(
            ctypes.windll.kernel32.GetLastError()))
    try:
        blob = ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
    return (base64.b64encode(blob).decode("ascii") if protect
            else blob.decode("utf-8"))


def dpapi_protect(plaintext):
    return _dpapi(True, plaintext)


def dpapi_unprotect(b64):
    return _dpapi(False, b64)


# ===========================================================================
# Naplo
# ===========================================================================

_LOG_PATH = None


def set_log(path):
    global _LOG_PATH
    _LOG_PATH = path


def log(msg):
    line = "{0} - {1}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ===========================================================================
# Alfolyamatok
# ===========================================================================

def _popen(args, env=None):
    flags = 0
    if os.name == "nt":
        flags = _CREATE_NO_WINDOW | _BELOW_NORMAL
    return subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=flags, env=env)


def _clean_err(err_bytes):
    err = err_bytes.decode("cp1250", "replace")
    return "\n".join(l for l in err.splitlines()
                     if l.strip() and BENIGN not in l)


def run_tool(cfg, exe, args, user_key="sysdba", stdin_text=None):
    """
    gsec / gbak / gstat hivasa. A hitelesites az ISC_USER / ISC_PASSWORD
    kornyezeti valtozon at megy, NEM a parancssoron - igy a jelszo nem
    latszik a folyamatlistaban (Feladatkezelo, wmic, Process Explorer).
    Visszaad: (returncode, stdout, stderr)
    """
    env = dict(os.environ)
    env["ISC_USER"] = cfg.user(user_key)
    env["ISC_PASSWORD"] = cfg.password(user_key)
    proc = _popen([cfg.tool(exe)] + list(args), env=env)
    data = stdin_text.encode("cp1250") if stdin_text is not None else None
    out, err = proc.communicate(input=data)
    return (proc.returncode, out.decode("cp1250", "replace"),
            _clean_err(err))


def run_isql(cfg, sql, user_key="olvas", commit=False):
    """
    Egy isql.exe futas. Visszaad: (stdout, stderr).

    FIGYELEM - az isql ket csapdaja (mindketto eles tapasztalat):
      * a QUIT VISSZAGORGETI a tranzakciot -> irasnal explicit COMMIT kell
      * hiba utan NEM all meg: a kovetkezo utasitas, koztuk a COMMIT is,
        lefut -> reszleges iras. Ezert a sikert soha ne a stderr-bol
        itelj meg, hanem uj kapcsolatbol visszaolvasva.
    """
    # SET NAMES a CONNECT ELOTT: az adatbazis WIN1250. Enelkul az ekezetes
    # literal hibasan tarolodik vagy hibat ad.
    connect = ("SET NAMES WIN1250;\n"
               "CONNECT 'localhost:{0}' USER '{1}' PASSWORD '{2}';\n").format(
        cfg.db_path, cfg.user(user_key), cfg.password(user_key))
    tail = "\nCOMMIT;\nQUIT;\n" if commit else "\nQUIT;\n"
    proc = _popen([cfg.isql])
    out, err = proc.communicate(input=(connect + sql + tail).encode("cp1250"))
    return out.decode("cp1250", "replace"), _clean_err(err)


def parse_list(raw, columns):
    """SET LIST ON kimenet -> [dict]. Ismeretlen sorokat kihagy."""
    names = dict((c.upper(), c) for c in columns)
    rows, cur = [], {}
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            if cur:
                rows.append(cur)
                cur = {}
            continue
        if s.startswith(("SQL>", "CON>", "Database:")):
            continue
        p = s.split(None, 1)
        key = p[0].upper()
        if key in names:
            if key in (k.upper() for k in cur):
                # ugyanaz az oszlop ujra: uj sor kezdodott ures sor nelkul
                rows.append(cur)
                cur = {}
            val = p[1].strip() if len(p) > 1 else ""
            cur[names[key]] = None if val == "<null>" else val
    if cur:
        rows.append(cur)
    return rows


def split_markers(raw):
    """
    A '@@nev@@' marker sorok menten felvagott kimenet: {nev: szoveg}.
    Igy egy isql-futasban sok lekerdezes mehet, es mindegyik kimenete
    kulon parszolhato. A marker: SELECT '@@nev@@' AS BLK FROM RDB$DATABASE;
    """
    chunks, name = {}, None
    for line in raw.splitlines():
        m = re.match(r"^BLK\s+@@(\w+)@@\s*$", line.strip())
        if m:
            name = m.group(1)
            chunks[name] = []
            continue
        if name is not None:
            chunks[name].append(line)
    return dict((k, "\n".join(v)) for k, v in chunks.items())


def marker(name):
    return "SELECT '@@{0}@@' AS BLK FROM RDB$DATABASE;".format(name)


def is_windows():
    return os.name == "nt"


def require_windows(what):
    if not is_windows():
        sys.exit("HIBA: a(z) {0} csak Windows-on (a POS gepen) "
                 "futtathato.".format(what))
