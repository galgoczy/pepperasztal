# -*- coding: utf-8 -*-
"""
felderites.py - CSAK OLVASO felderites a NovoHost adatbazison.

A VIP-app tervezese elott ezekre a kerdesekre kell valasz:

  1. Tetelesen latszik-e, mit vett a vendeg a VIP-kartyaval?
     (NYUGTAFIZETES.KKODID -> KARTYATORZS.ID)   -> pontgyujtes
  2. Van-e reszfizetes (VIP + keszpenz/kartya egy nyugtan)?
     Engedi-e a kassza a minusz egyenleget?      -> app UX
  3. Utkozik-e a 2-es EAN prefix a termek-vonalkodokkal?
  4. Hol el a napi etlap? Van-e ilyen tabla a NovoHostban?
  5. Igaz-e a LIMIT_KP - AKT_FORG = AKT_KP invarians minden kartyan?
  6. Mit csinal a LIMIT / LIMITALVA / KARTYAGYUJTO?
  7. Megvan-e meg a 610-es tesztkartya?
  8. Mely triggerek/eljarasok futnak le irasnal (-> milyen jog kell)?
  9. Kornyezet: InterBase verzio, ODS, dialektus, DB-meret, a 3050-es
     port kifele nyitva van-e, van-e nyoma mentesnek.
  10. Van-e azonos nevu kartya (pl. szemelyzeti + feltoltos)?
  11. Mit ellenoriznek a kartya-triggerek es az NH$CHK_DBL_VIP_CARD?

BIZTONSAG
  * A script minden utasitast ellenoriz: csak SELECT / SET LIST / SHOW
    mehet ki. Nincs COMMIT, a QUIT visszagorget. PEPPER_OLVAS-kent
    (alapertelmezes, ha van jelszava) maga az adatbazis is tiltja az irast.
  * SET TRANSACTION-t szandekosan NEM hasznalunk: az IB6 isql ilyenkor
    rakerdez ("Commit current transaction (y/n)?"), es a kovetkezo
    bemeneti sort veszi valasznak. Elesben ez a SET LIST ON-t nyelte el
    ("Rolling back work."), es minden lekerdezes parszolhatatlan lett.
  * Nyitvatartason kivul futtasd: nehany lekerdezes sok nyugtat olvas
    vegig. Csak indexelt tartomanyon (NYUGTAFIZETES.FEJ, NYUGTATETEL.FEJ)
    szurunk, de a POS gepet akkor se terheljuk feleslegesen.
  * A jelentes NEM tartalmaz nevet, kartyakodot, telefonszamot - csak
    darabszamokat, kartya-ID-kat es etelneveket. Nyugodtan tovabbithato.

FUTTATAS (a POS gepen, a pepper_agent.ini mellett):
    python felderites.py
    python felderites.py --nyugtak 50000      (kisebb ablak)
    python felderites.py --user sysdba        (ha PEPPER_OLVAS meg nincs)

Kimenet: felderites_<helyszin>_<datum>.txt a script mellett.
"""

import argparse
import datetime
import glob
import os
import re
import socket
import subprocess
import sys
import time

from common import (AGENT_VERSION, HERE, ConfigError, is_windows, load_config,
                    parse_list, run_isql, run_tool)

VIP = "N.FIZTIP = 'FIZ' AND N.FIZTIPID = 10"
IDENT = re.compile(r"^[A-Z0-9_$]+$")


# ===========================================================================
# Csak-olvaso orseg
# ===========================================================================

_ALLOWED = (
    re.compile(r"^SELECT\b", re.I),
    re.compile(r"^SET\s+LIST\s+ON$", re.I),
    re.compile(r"^SHOW\s+SQL\s+DIALECT$", re.I),
    # Egy trigger / tarolt eljaras forrasanak kiirasa (csak olvas).
    re.compile(r"^SHOW\s+(PROCEDURE|TRIGGER)\s+[A-Z0-9_$]+$", re.I),
)


class NotReadOnly(Exception):
    pass


def assert_readonly(sql):
    """
    Minden ';'-vel lezart utasitasnak az engedelyezett mintak egyikere kell
    illeszkednie. A sztring-literalokat elobb kivesszuk, hogy egy ';' vagy
    kulcsszo egy idezojelen belul ne zavarjon be.
    """
    stripped = re.sub(r"'(?:[^']|'')*'", "''", sql)
    for stmt in stripped.split(";"):
        s = " ".join(stmt.split())
        if not s:
            continue
        if not any(p.match(s) for p in _ALLOWED):
            raise NotReadOnly("Nem engedelyezett utasitas: " + s[:80])
        # SELECT-en belul se legyen iro kulcsszo (pl. egy
        # "SELECT ...; DELETE" probalkozas mar fent elbukik, ez a
        # beagyazott eljarashivast fogja meg).
        if re.search(r"\b(INSERT|UPDATE|DELETE|EXECUTE|GRANT|REVOKE|"
                     r"ALTER|CREATE|DROP|COMMIT)\b", s, re.I):
            raise NotReadOnly("Iro kulcsszo a lekerdezesben: " + s[:80])


class DB(object):
    """Lekerdezesek egy-egy kulon isql futasban, COMMIT nelkul."""

    def __init__(self, cfg, user_key):
        self.cfg = cfg
        self.user_key = user_key
        self.errors = []
        self.last_out = ""
        self.t0 = time.time()
        self.progress_path = os.path.join(HERE, "felderites_futas.txt")
        try:
            open(self.progress_path, "w").close()
        except Exception:
            self.progress_path = None

    def raw(self, sql):
        full = "SET LIST ON;\n" + sql
        assert_readonly(full)
        t = time.time()
        out, err = run_isql(self.cfg, full, user_key=self.user_key)
        self.last_out = out
        self.progress("{0:5.1f} mp  {1}".format(
            time.time() - t, " ".join(sql.split())[:70]))
        if err:
            self.errors.append((sql.strip()[:120], err))
        return out, err

    def progress(self, msg):
        """Futas kozbeni allapot a konzolra es a felderites_futas.txt-be,
        hogy egy lassu vagy megakadt lekerdezes azonnal latsszon."""
        line = "[{0:6.1f}] {1}".format(time.time() - self.t0, msg)
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
        if self.progress_path:
            try:
                with open(self.progress_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def rows(self, sql, cols):
        out, err = self.raw(sql)
        return parse_list(out, cols), err

    def one(self, sql, col):
        rows, err = self.rows(sql, [col])
        if not rows or rows[0].get(col) is None:
            return None, err
        return rows[0][col], err

    def num(self, sql, col="DB"):
        v, err = self.one(sql, col)
        try:
            return float(v) if v is not None and "." in v else (
                int(v) if v is not None else None), err
        except ValueError:
            return None, err


# ===========================================================================
# Jelentes
# ===========================================================================

class Report(object):
    def __init__(self):
        self.lines = []

    def h(self, title):
        self.lines += ["", "", "=" * 72, title, "=" * 72]

    def sub(self, title):
        self.lines += ["", "--- " + title]

    def kv(self, label, value):
        self.lines.append("  {0:<46} {1}".format(label, fmt(value)))

    def text(self, s=""):
        for l in s.splitlines() or [""]:
            self.lines.append("  " + l)

    def verdict(self, s):
        self.lines += ["", "  >> " + s]

    def err(self, err):
        if err:
            first = err.strip().splitlines()[0][:110]
            self.lines.append("  !! isql hiba: " + first)

    def __str__(self):
        return "\n".join(self.lines) + "\n"


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return "{0:,.0f}".format(v).replace(",", " ")
    if isinstance(v, int):
        return "{0:,}".format(v).replace(",", " ")
    return str(v)


def mask_digits(s):
    """
    Nyers tablakiirasnal: 8+ jegyu szamsor (kartyaszam, telefon) helyett
    csak a hossza latszik. Igy a jelentes akkor is tovabbithato, ha egy
    konfiguracios tablarol kiderul, hogy megis tarol ilyet.
    """
    return re.sub(r"\d{8,}", lambda m: "#" * len(m.group(0)), s)


def pct(a, b):
    if not a or not b:
        return "-"
    return "{0:.1f}%".format(100.0 * a / b)


# ===========================================================================
# 0. Kornyezet (adatbazis nelkul)
# ===========================================================================

def sec_kornyezet(cfg, rep, tools_ok, db):
    rep.h("0. KORNYEZET")
    rep.kv("Gep", socket.gethostname())
    rep.kv("Helyszin (ini)", cfg.helyszin or "-")
    rep.kv("Futtatas ideje", time.strftime("%Y-%m-%d %H:%M"))
    rep.kv("Python", sys.version.split()[0])

    if os.path.exists(cfg.db_path):
        st = os.stat(cfg.db_path)
        rep.kv("novohost.ib merete (MB)", round(st.st_size / 1048576.0, 1))
        rep.kv("novohost.ib utolso modositas",
               time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)))
        try:
            import shutil
            free = shutil.disk_usage(os.path.dirname(cfg.db_path)).free
            rep.kv("Szabad hely a DB lemezen (MB)", int(free / 1048576))
        except Exception:
            pass
    else:
        rep.kv("novohost.ib", "NEM TALALOM: " + cfg.db_path)

    # isql verzio: a -z kapcsolo kiirja, majd a QUIT-tel kilep.
    try:
        p = subprocess.Popen([cfg.isql, "-z"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate(b"QUIT;\n")
        ver = [l.strip() for l in out.decode("cp1250", "replace").splitlines()
               if "version" in l.lower()]
        rep.kv("isql verzio", ver[0] if ver else "?")
    except Exception as e:
        rep.kv("isql verzio", "nem futtathato: {0}".format(e))

    # gstat -h: a fejlec-lap. ODS, lapmeret, dialektus. SYSDBA kell hozza.
    if tools_ok:
        try:
            rc, out, err = run_tool(cfg, "gstat.exe" if is_windows() else
                                    "gstat", ["-h", cfg.db_path])
            for key in ("ODS version", "Page size", "Database dialect",
                        "Oldest transaction", "Next transaction",
                        "Creation date"):
                m = re.search(r"^\s*" + key + r"\s+(.+)$", out, re.M)
                if m:
                    rep.kv("gstat: " + key, m.group(1).strip())
            if rc and err:
                rep.err(err)
        except Exception as e:
            rep.kv("gstat", "nem futtathato: {0}".format(e))
    else:
        rep.kv("gstat", "kihagyva (nincs SYSDBA jelszo az ini-ben)")

    out, _ = db.raw("SHOW SQL DIALECT;")
    dia = [l.replace("SQL>", "").strip() for l in out.splitlines()
           if "dialect" in l.lower()]
    rep.kv("SQL dialektus", dia[0][:90] if dia else "?")

    # A 3050-es port: ha 0.0.0.0-n hallgat, a LAN-rol elerheto.
    rep.sub("InterBase port (3050)")
    if is_windows():
        try:
            out = subprocess.check_output(["netstat", "-an"]).decode(
                "cp852", "replace")
            hits = sorted(set(" ".join(l.split()[:2]) for l in out.splitlines()
                              if ":3050 " in l + " " and
                              ("LISTEN" in l.upper() or "FIGYEL" in l.upper())))
            for h in hits:
                rep.text(h)
            # Kik kapcsolodnak most a 3050-hez? Ha mas IP is van, az egy
            # masik kassza/terminal - a portot NEM szabad vakon lezarni.
            peers = set()
            for l in out.splitlines():
                p = l.split()
                if len(p) >= 4 and p[1].endswith(":3050") and \
                        not p[2].startswith(("0.0.0.0", "[::]", "*")):
                    ip = p[2].rsplit(":", 1)[0]
                    if ip not in ("127.0.0.1", "[::1]"):
                        peers.add(ip)
            rep.kv("Tavoli gepek, amik most a 3050-hez kapcsolodnak",
                   ", ".join(sorted(peers)) or "nincs")
            if any("0.0.0.0:3050" in h or "[::]:3050" in h for h in hits):
                rep.verdict(
                    "A 3050-es port MINDEN interfeszen hallgat. A SYSDBA "
                    "jelszo kiszivargott, ezert a portot a fenti tavoli "
                    "gepeken (masik kassza) KIVUL senki ne erje el. Vakon "
                    "lezarni TILOS, az a tobbi kasszat is leallitana. "
                    "Lasd README.")
            elif hits:
                rep.verdict("Csak helyi cimen hallgat - jo.")
            else:
                rep.text("Nem talaltam figyelo 3050-es portot.")
        except Exception as e:
            rep.text("netstat hiba: {0}".format(e))
        for cmd in (["netsh", "advfirewall", "show", "allprofiles", "state"],
                    ["netsh", "firewall", "show", "state"]):
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                rep.sub("Tuzfal (" + " ".join(cmd[1:3]) + ")")
                for l in out.decode("cp852", "replace").splitlines():
                    if l.strip() and not l.startswith("-"):
                        rep.text(l.strip())
                break
            except Exception:
                continue
    else:
        rep.text("(nem Windows - kihagyva)")

    # Mentes nyomai: a DB mappajaban es szuloben.
    rep.sub("Mentes nyomai a DB mellett")
    d = os.path.dirname(cfg.db_path)
    found = []
    for base in (d, os.path.dirname(d)):
        for pat in ("*.gbk", "*.gbak", "*.fbk", "*.bak", "*backup*", "*mentes*"):
            found += glob.glob(os.path.join(base, pat))
    if found:
        found = sorted(set(found), key=os.path.getmtime, reverse=True)
        for f in found[:8]:
            rep.text("{0}  {1}".format(time.strftime(
                "%Y-%m-%d", time.localtime(os.path.getmtime(f))), f))
    else:
        rep.text("Nem talaltam (ez nem bizonyitja, hogy mashol sincs).")


# ===========================================================================
# 1-2. Fizetesek: egyszeru lekerdezesek, a parositas Pythonban
# ===========================================================================
#
# Az IB6 optimalizalo a beagyazott (korrelalt) EXISTS lekerdezeseket
# rosszul viseli: elesben egy kis adatbazison is percekig futott. Ezert az
# adatbazistol csak egyszeru, indexelt tartomany-lekerdezeseket kerunk
# (NYUGTAFIZETES.FEJ, NYUGTATETEL.FEJ), illetve kis tablakat olvasunk be
# egeszben (KARTYATORZS, KARTYANAPLO, ETELFAJ). A parositas a memoriaban
# tortenik. Nev es kartyakod csak itt, osszevetesre kerul elo - a
# jelentesbe nem kerul.

def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v):
    return (v or "").strip()


def _ts(v):
    """isql TIMESTAMP ('2017-01-09 16:23:07.0000') -> datetime vagy None."""
    try:
        return datetime.datetime.strptime(_s(v)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _fk_by_card(d):
    by = {}
    for r in d["naplo"]:
        if _s(r.get("T")) == "FK":
            by.setdefault(_i(r.get("K")), []).append(
                (_ts(r.get("D")), _f(r.get("O"))))
    return by


def load_fizetesek(db, lo, lo_kicsi):
    d = {}
    # VIP-fizetesek a nagy ablakban - csak ezek a sorok (FEJ index).
    rows, e = db.rows(
        "SELECT N.FEJ AS FEJ, N.FIZTIP AS FT, N.KKODID AS KID, N.FORINT AS "
        "FORINT, N.KKOD AS KKOD, N.KTULAJDONOS AS KTUL FROM NYUGTAFIZETES N "
        "WHERE N.FEJ > {0} AND N.FIZTIPID = 10;".format(lo),
        ["FEJ", "FT", "KID", "FORINT", "KKOD", "KTUL"])
    d["vip_err"] = e
    d["vip"] = [r for r in rows if _s(r.get("FT")) == "FIZ"]

    # Kartyak (nehany tucat sor).
    rows, e = db.rows("SELECT K.ID AS ID, K.TIPUS AS TIPUS, K.KARTYA AS "
                      "KOD, K.NEV AS NEV, K.AKT_KP AS AKT FROM KARTYATORZS K;",
                      ["ID", "TIPUS", "KOD", "NEV", "AKT"])
    d["kartyak"] = dict((_i(r.get("ID")), r) for r in rows)

    # Kartyanaplo egeszben (nehany tizezer sor).
    rows, e = db.rows("SELECT L.ID AS ID, L.KARTYA AS K, L.TTIPUS AS T, "
                      "L.OSSZEG AS O, L.AKT AS A, L.DATUM AS D "
                      "FROM KARTYANAPLO L;", ["ID", "K", "T", "O", "A", "D"])
    d["naplo"] = rows

    # A kis ablak minden fizetese (vegyes fizeteshez) es tetele.
    rows, e = db.rows(
        "SELECT N.FEJ AS FEJ, N.FIZTIP AS FT, N.FIZTIPID AS FID, N.ELOJEL AS "
        "EL, N.FORINT AS FORINT FROM NYUGTAFIZETES N WHERE N.FEJ > {0};"
        .format(lo_kicsi), ["FEJ", "FT", "FID", "EL", "FORINT"])
    d["fiz_kicsi"] = rows
    rows, e = db.rows(
        "SELECT F.ID AS ID, F.VEGERTEK AS VE, F.LEZARVA AS LZ FROM NYUGTAFEJ F "
        "WHERE F.ID > {0};".format(lo_kicsi), ["ID", "VE", "LZ"])
    d["fej_kicsi"] = dict((_i(r.get("ID")), r) for r in rows)
    rows, e = db.rows("SELECT T.FEJ AS FEJ, T.EAZO AS E FROM NYUGTATETEL T "
                      "WHERE T.FEJ > {0};".format(lo_kicsi), ["FEJ", "E"])
    d["tetel_kicsi"] = rows
    rows, e = db.rows("SELECT E.ID AS ID, E.NEV AS NEV FROM ETELFAJ E;",
                      ["ID", "NEV"])
    d["etelfaj"] = dict((_i(r.get("ID")), _s(r.get("NEV"))) for r in rows)
    return d


def sec_kkodid(d, rep, lo, lo_kicsi, nyugtak):
    rep.h("1. TETELES VASARLASTORTENET (NYUGTAFIZETES.KKODID)")
    rep.text("Nagy ablak: az utolso {0} nyugta (NYUGTAFEJ.ID > {1}); "
             "kis ablak: NYUGTAFEJ.ID > {2}.".format(fmt(nyugtak), fmt(lo),
                                                     fmt(lo_kicsi)))
    rep.err(d["vip_err"])
    vip, kartyak = d["vip"], d["kartyak"]
    ossz = len(vip)
    rep.kv("VIP-fizetes sor", ossz)
    if not ossz:
        rep.verdict("Az ablakban nincs VIP-fizetes - novelj --nyugtak-ot.")
        return

    kids = [_i(v.get("KID")) for v in vip]
    nn = sum(1 for k in kids if k is not None)
    rep.kv("  ebbol KKODID kitoltve", "{0}  ({1})".format(fmt(nn),
                                                          pct(nn, ossz)))
    present = [k for k in kids if k is not None]
    if present:
        rep.kv("  KKODID tartomany", "{0} .. {1}".format(min(present),
                                                         max(present)))
    kid = sum(1 for k in kids if k in kartyak)
    rep.kv("  KKODID = egy letezo KARTYATORZS.ID",
           "{0}  ({1})".format(fmt(kid), pct(kid, ossz)))
    kkod = sum(1 for v in vip if _i(v.get("KID")) in kartyak and
               _s(kartyak[_i(v.get("KID"))].get("KOD")) == _s(v.get("KKOD")))
    rep.kv("  ... es KKOD = a kartya kodja", "{0}  ({1})".format(
        fmt(kkod), pct(kkod, ossz)))
    knev = sum(1 for v in vip if _i(v.get("KID")) in kartyak and
               _s(kartyak[_i(v.get("KID"))].get("NEV")) == _s(v.get("KTUL")))
    rep.kv("  ... es KTULAJDONOS = a kartya neve", "{0}  ({1})".format(
        fmt(knev), pct(knev, ossz)))

    fk = set()
    for r in d["naplo"]:
        if _s(r.get("T")) == "FK" and _f(r.get("O")) is not None:
            fk.add((_i(r.get("K")), int(round(abs(_f(r.get("O")))))))
    kicsi = [v for v in vip if (_i(v.get("FEJ")) or 0) > lo_kicsi]
    kegy = sum(1 for v in kicsi if _f(v.get("FORINT")) is not None and
               (_i(v.get("KID")), int(round(abs(_f(v.get("FORINT")))))) in fk)
    rep.kv("  kis ablakban: egyezo FK naplosor",
           "{0} / {1}  ({2})".format(fmt(kegy), fmt(len(kicsi)),
                                     pct(kegy, len(kicsi))))

    tetel_fej = set(_i(t.get("FEJ")) for t in d["tetel_kicsi"])
    tet = sum(1 for v in kicsi if _i(v.get("FEJ")) in tetel_fej)
    rep.kv("  kis ablakban: van NYUGTATETEL a nyugtan",
           "{0} / {1}  ({2})".format(fmt(tet), fmt(len(kicsi)),
                                     pct(tet, len(kicsi))))

    ok = kid >= 0.95 * ossz
    tet_ok = kicsi and tet >= 0.95 * len(kicsi)
    if ok and tet_ok:
        rep.verdict("IGEN - a KKODID a kartyara mutat, a nyugtan tetelek "
                    "vannak. Tetelalapu pontgyujtes megoldhato.")
    elif ok:
        rep.verdict("A KKODID a kartyara mutat, de a tetelek hianyosak (vagy "
                    "a kis ablakban nincs VIP-fizetes) - nezd meg kezzel.")
    else:
        rep.verdict("NEM bizonyitott. A pontgyujtest ertekalapura kell "
                    "tervezni (pl. 100 Ft = 1 pont) a KARTYANAPLO-bol.")

    # Mit vesznek VIP-pel - csak etelnevek, nincs vendegadat.
    rep.sub("Leggyakoribb tetelek VIP-pel fizetett nyugtakon (kis ablak)")
    vip_fej = set(_i(v.get("FEJ")) for v in kicsi)
    cnt = {}
    for t in d["tetel_kicsi"]:
        if _i(t.get("FEJ")) in vip_fej:
            nev = d["etelfaj"].get(_i(t.get("E")), "?")
            cnt[nev] = cnt.get(nev, 0) + 1
    for nev, n in sorted(cnt.items(), key=lambda x: -x[1])[:15]:
        rep.text("{0:>6}  {1}".format(n, nev))
    if not cnt:
        rep.text("(nincs adat a kis ablakban)")


def sec_minta(d, rep):
    """
    Hogyan kapcsolodik egy VIP-fizetes a kartyanaplohoz? Minden kis ablakos
    VIP-fizeteshez keresunk ugyanannak a kartyanak +-15 percen beluli FK
    sorat, es megnezzuk, mihez egyezik az osszege. Kartyatipusonkent, mert
    a szemelyzeti kartya (4) 0 Ft-ot fizet.
    """
    rep.h("1b. VIP-FIZETES ES KARTYANAPLO OSSZEVETESE (kis ablak)")
    fk = _fk_by_card(d)
    fej = d["fej_kicsi"]
    win = datetime.timedelta(minutes=15)
    stat = {}
    minta = []
    for v in sorted(d["vip"], key=lambda x: -(_i(x.get("FEJ")) or 0)):
        f = _i(v.get("FEJ"))
        if f not in fej:
            continue
        kid = _i(v.get("KID"))
        tip = _s(d["kartyak"].get(kid, {}).get("TIPUS")) or "?"
        lz = _ts(fej[f].get("LZ"))
        ve = _f(fej[f].get("VE"))
        ft = _f(v.get("FORINT"))
        near = [o for (t, o) in fk.get(kid, [])
                if t and lz and abs(t - lz) <= win and o is not None]
        st = stat.setdefault(tip, {"n": 0, "ido": 0, "forint": 0,
                                   "vegertek": 0, "nulla": 0})
        st["n"] += 1
        if near:
            st["ido"] += 1
            if ft is not None and any(abs(abs(o) - abs(ft)) < 0.5 for o in near):
                st["forint"] += 1
            if ve is not None and any(abs(abs(o) - abs(ve)) < 0.5 for o in near):
                st["vegertek"] += 1
            if any(abs(o) < 0.5 for o in near):
                st["nulla"] += 1
        if len([m for m in minta if m[1] == tip]) < 4:
            minta.append((f, tip, kid, lz, ve, ft, near))

    rep.text("tipus    VIP-fiz.  van FK +-15p  FK=FORINT  FK=VEGERTEK  FK=0")
    for tip in sorted(stat):
        st = stat[tip]
        rep.text("{0:>5}  {1:>10}  {2:>12}  {3:>9}  {4:>11}  {5:>4}".format(
            tip, st["n"], st["ido"], st["forint"], st["vegertek"],
            st["nulla"]))
    rep.text("(1 = Feltolto, 4 = Szemelyzet)")
    t1 = stat.get("1")
    if t1 and t1["n"] and t1["forint"] >= 0.95 * t1["n"]:
        rep.verdict("Feltolto kartyanal minden VIP-fizeteshez van FK naplosor "
                    "pontosan ugyanazzal az osszeggel -> a koltes-ertesites a "
                    "KARTYANAPLO figyelesere epulhet.")
    t4 = stat.get("4")
    if t4 and t4["n"] and not t4["ido"]:
        rep.text("A szemelyzeti kartya (4) nem ir naplosort - a fogyasztasa "
                 "az AKT_FORG-ban halmozodik.")

    rep.sub("Minta: legutobbi VIP-nyugtak tipusonkent (csak osszegek)")
    by_fej = {}
    for r in d["fiz_kicsi"]:
        by_fej.setdefault(_i(r.get("FEJ")), []).append(r)
    for f, tip, kid, lz, ve, ft, near in minta:
        rep.text("nyugta {0}  kartya {1} (tipus {2})  {3}  vegertek {4}".format(
            f, kid, tip, lz.strftime("%Y-%m-%d %H:%M") if lz else "?",
            fmt(ve)))
        sorok = ["{0}/{1} {2}{3}".format(_s(r.get("FT")), _i(r.get("FID")),
                                        "+" if (_i(r.get("EL")) or 0) >= 0
                                        else "-", fmt(_f(r.get("FORINT"))))
                 for r in by_fej.get(f, []) if _s(r.get("FT")) != "AFA"]
        rep.text("    fizetesi sorok: " + ", ".join(sorok))
        rep.text("    FK naplo +-15p: " + (", ".join(fmt(o) for o in near)
                                           or "nincs"))


def sec_naplo_invarians(d, rep):
    """A kartya egyenlege = az utolso naplosor utani egyenleg (AKT+OSSZEG)?"""
    rep.h("5b. EGYENLEG A NAPLO SZERINT: AKT_KP = utolso naplosor AKT + OSSZEG")
    last = {}
    for r in d["naplo"]:
        k, i = _i(r.get("K")), _i(r.get("ID"))
        if k is not None and i is not None and (k not in last or
                                                i > last[k][0]):
            last[k] = (i, _f(r.get("A")), _f(r.get("O")), _s(r.get("T")))
    stat, rossz = {}, []
    for kid, k in d["kartyak"].items():
        tip = _s(k.get("TIPUS")) or "?"
        st = stat.setdefault(tip, [0, 0, 0])
        st[0] += 1
        if kid not in last:
            st[2] += 1
            continue
        _, a, o, t = last[kid]
        akt = _f(k.get("AKT"))
        if None in (a, o, akt):
            continue
        if abs(a + o - akt) < 0.5:
            st[1] += 1
        else:
            rossz.append((kid, tip, t, a + o, akt))
    rep.text("tipus  kartya  egyezik  nincs naplosora")
    for tip in sorted(stat):
        rep.text("{0:>5}  {1:>6}  {2:>7}  {3:>15}".format(tip, *stat[tip]))
    for kid, tip, t, vart, akt in rossz[:20]:
        rep.text("ID {0:>5}  tipus {1}  utolso: {2}  naplo szerint {3}  "
                 "AKT_KP {4}".format(kid, tip, t, fmt(vart), fmt(akt)))
    if not rossz:
        rep.verdict("Minden naploval rendelkezo kartyan egyezik - a napi "
                    "egyeztetes erre epulhet (a LIMIT_KP-s invarians helyett).")
    else:
        rep.verdict("Nem mindenhol egyezik - meg kell nezni, milyen mozgas "
                    "nem kerul a naploba.")


def sec_reszfizetes(d, rep, db):
    rep.h("2. RESZFIZETES ES MINUSZ EGYENLEG")
    rep.text("A kis ablak alapjan. Fizetesi sor csak a FIZ tipus; az AFA sorok "
             "AFA-bontasok, a KER valoszinuleg kerekites.")
    by_fej = {}
    for r in d["fiz_kicsi"]:
        by_fej.setdefault(_i(r.get("FEJ")), []).append(r)

    def fiz(r):
        return _s(r.get("FT")) == "FIZ"

    vip_fej = [f for f, rs in by_fej.items()
               if any(fiz(r) and _i(r.get("FID")) == 10 for r in rs)]
    fej_tipus = {}
    for v in d["vip"]:
        k = d["kartyak"].get(_i(v.get("KID")), {})
        fej_tipus[_i(v.get("FEJ"))] = _s(k.get("TIPUS")) or "?"
    vegyes, nullas, bontas, nemfiz, vegyes_tip = 0, 0, {}, {}, {}
    for f in vip_fej:
        mas = [r for r in by_fej[f] if fiz(r) and _i(r.get("FID")) != 10]
        valodi = [r for r in mas if abs(_f(r.get("FORINT")) or 0) >= 0.5]
        if valodi:
            vegyes += 1
            t = fej_tipus.get(f, "?")
            vegyes_tip[t] = vegyes_tip.get(t, 0) + 1
        if mas and not valodi:
            nullas += 1
        for r in valodi:
            k = (_i(r.get("FID")), _i(r.get("EL")))
            n, sm = bontas.get(k, (0, 0.0))
            bontas[k] = (n + 1, sm + (_f(r.get("FORINT")) or 0))
        for r in by_fej[f]:
            if not fiz(r):
                k = _s(r.get("FT"))
                nemfiz[k] = nemfiz.get(k, 0) + 1
    vf = len(vip_fej)
    rep.kv("Nyugta VIP-fizetessel", vf)
    rep.kv("  ebbol mas, NEM NULLA fizetes is van rajta",
           "{0}  ({1})".format(fmt(vegyes), pct(vegyes, vf)))
    rep.kv("  ebbol csak 0 Ft-os mas fizetesi sor van", fmt(nullas))
    if vegyes_tip:
        rep.kv("  vegyes fizetes kartyatipusonkent", ", ".join(
            "tipus {0}: {1}".format(t, n) for t, n in sorted(vegyes_tip.items())))
    if bontas:
        rep.sub("A VIP melletti valodi fizetesek bontasa")
        rep.text("FIZTIPID  ELOJEL      DB     OSSZEG   (0 keszp., 3 bankkartya,"
                 " 8 SZEP)")
        for (fid, el), (n, sm) in sorted(bontas.items(), key=lambda x: -x[1][0]):
            rep.text("{0:>8}  {1:>6}  {2:>6}  {3:>9}".format(fid, el, n,
                                                           fmt(sm)))
    if nemfiz:
        rep.text("Nem fizetesi sorok a VIP-nyugtakon: " + ", ".join(
            "{0}: {1}".format(k, n) for k, n in sorted(nemfiz.items())))
    if vegyes:
        rep.verdict("Van VIP + mas fizetesi mod ugyanazon a nyugtan, nem "
                    "nulla osszeggel. Ha az ELOJEL pozitiv, a kassza tud "
                    "reszfizetest (negativ: visszajaro).")
    elif vf:
        rep.verdict("Nincs valodi vegyes fizetes: a VIP-nyugtakon a tobbi "
                    "fizetesi sor 0 Ft. Valoszinuleg nincs reszfizetes - az "
                    "appban jelezni kell, ha az egyenleg nem eleg.")

    rep.sub("Minusz egyenleg")
    fk = [r for r in d["naplo"] if _s(r.get("T")) == "FK"]
    pos = sum(1 for r in fk if (_f(r.get("O")) or 0) > 0)
    rep.kv("FK sor osszesen / pozitiv osszeggel", "{0} / {1}".format(
        fmt(len(fk)), fmt(pos)))
    minusz = {}
    for r in fk:
        o, a = _f(r.get("O")), _f(r.get("A"))
        if o is not None and a is not None and a + o < -0.5:
            k = d["kartyak"].get(_i(r.get("K")), {})
            t = _s(k.get("TIPUS")) or "?"
            minusz[t] = minusz.get(t, 0) + 1
    if minusz:
        for t, n in sorted(minusz.items()):
            rep.kv("  FK utan minuszba ment (kartyatipus {0})".format(t), n)
    else:
        rep.kv("  FK utan minuszba ment", 0)
    neg, e = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS WHERE AKT_KP < 0;")
    rep.kv("Kartya most minuszban (AKT_KP < 0)", neg)
    # A 4-es tipus a szemelyzeti kartya (ENGEDMENY=100, 0 Ft-ot fizet) -
    # az o minuszuk nem mond semmit a vendegkartyakrol.
    vendeg_minusz = dict((t, n) for t, n in minusz.items() if t != "4")
    if vendeg_minusz and pos == 0:
        rep.verdict("A kassza ENGEDI a minuszt vendegkartyan is. Prepaid-nel "
                    "ezt le kell zarni - limit vagy kezeloi szabaly kell.")
    elif minusz and pos == 0:
        rep.verdict("Csak szemelyzeti kartya (4-es tipus) ment minuszba - "
                    "vendegkartyan nem fordult elo.")
    elif fk and pos == 0:
        rep.verdict("Soha nem ment minuszba: a kassza valoszinuleg nem "
                    "engedi tulkolteni.")


# ===========================================================================
# 3. EAN-utkozes
# ===========================================================================

def sec_ean(db, rep):
    rep.h("3. EAN-13 '2' PREFIX - UTKOZES A MEGLEVO KODOKKAL")
    cols, e = db.rows(
        "SELECT RF.RDB$RELATION_NAME AS TABLA, RF.RDB$FIELD_NAME AS MEZO "
        "FROM RDB$RELATION_FIELDS RF "
        "JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME = RF.RDB$RELATION_NAME "
        "JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME = RF.RDB$FIELD_SOURCE "
        "WHERE (R.RDB$SYSTEM_FLAG IS NULL OR R.RDB$SYSTEM_FLAG = 0) "
        "AND R.RDB$VIEW_BLR IS NULL AND F.RDB$FIELD_TYPE IN (14, 37) "
        "AND (RF.RDB$FIELD_NAME LIKE '%VONAL%' OR RF.RDB$FIELD_NAME "
        "LIKE '%EAN%' OR RF.RDB$FIELD_NAME LIKE '%BARCODE%');",
        ["TABLA", "MEZO"])
    rep.err(e)
    targets = [(c["TABLA"].strip(), c["MEZO"].strip()) for c in cols
               if c.get("TABLA") and c.get("MEZO")]
    targets.append(("KARTYATORZS", "KARTYA"))
    rep.text("Vizsgalt mezok: " + ", ".join(t + "." + m for t, m in targets))
    rep.text("")
    rep.text("{0:<34} {1:>8} {2:>8} {3:>8}".format(
        "tabla.mezo", "kitolt.", "'2..'", "';2..'"))
    used2, used3, hossz, used2_13 = {}, set(), {}, {}
    for t, m in targets:
        if not (IDENT.match(t) and IDENT.match(m)):
            continue
        r, e = db.rows((
            "SELECT "
            "(SELECT COUNT(*) FROM {0} WHERE {1} IS NOT NULL AND {1} <> '') AS A,"
            "(SELECT COUNT(*) FROM {0} WHERE {1} STARTING WITH '2') AS B,"
            "(SELECT COUNT(*) FROM {0} WHERE {1} STARTING WITH ';2') AS D "
            "FROM RDB$DATABASE;").format(t, m), ["A", "B", "D"])
        if not r:
            rep.err(e)
            continue
        x = r[0]
        rep.text("{0:<34} {1:>8} {2:>8} {3:>8}".format(
            (t + "." + m)[:34], x.get("A"), x.get("B"), x.get("D")))
        if t == "KARTYATORZS":
            continue      # kartyakodokat nem olvasunk ki
        vals, e = db.rows("SELECT {1} AS V FROM {0} WHERE {1} STARTING WITH "
                          "'2';".format(t, m), ["V"])
        for v in vals:
            c = _s(v.get("V"))
            if len(c) >= 3:
                used2[c[:2]] = used2.get(c[:2], 0) + 1
                used3.add(c[:3])
                hossz[len(c)] = hossz.get(len(c), 0) + 1
                if len(c) == 13 and c.isdigit():
                    used2_13[c[:2]] = used2_13.get(c[:2], 0) + 1
    rep.sub("Termekkodok '2' kezdettel")
    if hossz:
        rep.text("Kodhosszak: " + ", ".join("{0} jegy: {1}".format(k, n)
                                            for k, n in sorted(hossz.items())))
    ean13 = used2_13
    rep.kv("13 jegyu (EAN-13) kod '2' kezdettel", sum(ean13.values()))
    if ean13:
        rep.text("  2 jegyu prefixek: " + "  ".join(
            "{0}:{1}".format(p, ean13.get(p, 0))
            for p in ["2" + str(i) for i in range(10)]))
        szabad = [p for p in ["2" + str(i) for i in range(10)]
                  if p not in ean13]
        rep.kv("  szabad 2 jegyu EAN-prefix", ", ".join(szabad) or "nincs")
        rep.verdict("Van 13 jegyu '2'-es kod - a kartyakod csak szabad "
                    "prefixszel keszulhet.")
    else:
        rep.verdict("Nincs 13 jegyu '2'-es kod: a rovid (3-4 jegyu) gyorskodok "
                    "pontos egyezesnel nem utkozhetnek egy 13 jegyu "
                    "kartyakoddal. A prefix tehat szabadon valaszthato - a "
                    "kerdes az, hogyan kezeli a kassza a beolvasott kodot.")
    rep.text("")
    rep.text("Nyitott (csak elo teszttel): megtalalja-e a kassza a beolvasott "
             "kodot pontos egyezessel a KARTYA mezoben.")


# ===========================================================================
# 4. Etlap
# ===========================================================================

def sec_etlap(db, rep):
    rep.h("4. HOL EL A NAPI ETLAP?")
    rows, e = db.rows(
        "SELECT R.RDB$RELATION_NAME AS TABLA FROM RDB$RELATIONS R "
        "WHERE (R.RDB$SYSTEM_FLAG IS NULL OR R.RDB$SYSTEM_FLAG = 0) AND ("
        "R.RDB$RELATION_NAME LIKE '%MENU%' OR R.RDB$RELATION_NAME LIKE "
        "'%ETLAP%' OR R.RDB$RELATION_NAME LIKE '%HETI%' OR "
        "R.RDB$RELATION_NAME LIKE '%NAPIMENU%' OR R.RDB$RELATION_NAME LIKE "
        "'%AJANLAT%' OR R.RDB$RELATION_NAME LIKE '%NAPTAR%');", ["TABLA"])
    rep.err(e)
    names = [r["TABLA"].strip() for r in rows if r.get("TABLA")]
    if not names:
        rep.text("Nincs MENU / ETLAP / HETI / AJANLAT / NAPTAR nevu tabla.")
    for t in names:
        if not IDENT.match(t):
            continue
        n, e = db.num("SELECT COUNT(*) AS DB FROM {0};".format(t))
        cols, _ = db.rows(
            "SELECT RDB$FIELD_NAME AS MEZO FROM RDB$RELATION_FIELDS "
            "WHERE RDB$RELATION_NAME = '{0}' ORDER BY RDB$FIELD_POSITION;"
            .format(t), ["MEZO"])
        rep.kv(t, "{0} sor".format(fmt(n)))
        rep.text("    " + ", ".join(c["MEZO"].strip() for c in cols
                                    if c.get("MEZO")))

    rep.sub("ETELFAJ (a kassza termeklistaja)")
    a, _ = db.num("SELECT COUNT(*) AS DB FROM ETELFAJ;")
    b, _ = db.num("SELECT COUNT(*) AS DB FROM ETELFAJ WHERE TOROLVE = 0 "
                  "OR TOROLVE IS NULL;")
    rep.kv("Tetel osszesen / nem torolt", "{0} / {1}".format(fmt(a), fmt(b)))
    rows, e = db.rows(
        "SELECT E.TIPUS AS TIPUS, COUNT(*) AS DB FROM ETELFAJ E WHERE "
        "E.TOROLVE = 0 OR E.TOROLVE IS NULL GROUP BY E.TIPUS;",
        ["TIPUS", "DB"])
    rep.err(e)
    if rows:
        rep.text("Nem torolt tetelek tipusonkent (ETELFAJ.TIPUS -> ETELTIP):")
        rep.text("  " + "  ".join("{0}:{1}".format(r.get("TIPUS"), r.get("DB"))
                                  for r in rows))
    rep.sub("ETELTIP (tetelkategoriak - a pontszabalyokhoz)")
    tipdb = dict((_i(r.get("TIPUS")), _i(r.get("DB"))) for r in rows)
    tips, e = db.rows("SELECT T.ID AS ID, T.NEV AS NEV FROM ETELTIP T "
                      "ORDER BY T.ID;", ["ID", "NEV"])
    rep.err(e)
    rep.text("  ID  kategoria                  aktiv tetel")
    for t in tips:
        rep.text("{0:>4}  {1:<26} {2:>6}".format(
            t.get("ID"), _s(t.get("NEV"))[:26],
            tipdb.get(_i(t.get("ID")), 0)))

    rep.verdict("Ha fent nincs datumozott menu-tabla, a napi etlap NEM a "
                "NovoHostban el. A korabban kapott Knorr menu-dump "
                "PostgreSQL (products/menus tablak) - az a forras.")


# ===========================================================================
# 5-7. Kartyak: invarians, limitek, tesztkartya
# ===========================================================================

def sec_kartyak(db, rep):
    rep.h("5. INVARIANS: LIMIT_KP - AKT_FORG = AKT_KP")
    ossz, e = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS;")
    rep.err(e)
    rep.kv("Kartya osszesen", ossz)
    rows, e = db.rows(
        "SELECT K.ID AS ID, K.TIPUS AS TIPUS, "
        "K.LIMIT_KP - K.AKT_FORG - K.AKT_KP AS ELTERES FROM KARTYATORZS K "
        "WHERE K.LIMIT_KP - K.AKT_FORG - K.AKT_KP > 0.5 "
        "OR K.LIMIT_KP - K.AKT_FORG - K.AKT_KP < -0.5 ORDER BY K.ID;",
        ["ID", "TIPUS", "ELTERES"])
    rep.err(e)
    nul, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS WHERE "
                    "LIMIT_KP IS NULL OR AKT_FORG IS NULL OR AKT_KP IS NULL;")
    rep.kv("Serto kartya", len(rows))
    rep.kv("NULL valamelyik mezoben", nul)
    for r in rows[:40]:
        rep.text("ID {0:>6}  tipus {1:>2}  elteres {2}".format(
            r.get("ID"), r.get("TIPUS"), r.get("ELTERES")))
    if not rows and not nul:
        rep.verdict("Minden kartyan igaz - a napi egyeztetes erre epulhet.")
    else:
        rep.verdict("Nem minden kartyan igaz. A szemelyzeti kartyaknal (4) ez "
                    "vart: a fogyasztasuk az AKT_FORG-ban halmozodik. A napi "
                    "egyeztetes az 5b szakasz szerinti szabalyra epuljon.")

    rep.h("6. LIMIT / LIMITALVA / KARTYATIPUS / KARTYAGYUJTO")
    rows, e = db.rows(
        "SELECT TIPUS AS TIPUS, LIMITALVA AS LIMITALVA, COUNT(*) AS DB "
        "FROM KARTYATORZS GROUP BY TIPUS, LIMITALVA;",
        ["TIPUS", "LIMITALVA", "DB"])
    rep.err(e)
    rep.text("TIPUS  LIMITALVA   DB")
    for r in rows:
        rep.text("{0:>5}  {1:>9}  {2:>3}".format(
            r.get("TIPUS"), r.get("LIMITALVA"), r.get("DB")))
    lim, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS WHERE LIMIT > 0;")
    tul, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS "
                    "WHERE LIMIT > 0 AND AKT_FORG > LIMIT;")
    mm, _ = db.rows("SELECT MIN(AKT_FORG) AS MN, MAX(AKT_FORG) AS MX "
                    "FROM KARTYATORZS;", ["MN", "MX"])
    rep.kv("Kartya LIMIT > 0", lim)
    rep.kv("  ebbol AKT_FORG > LIMIT", tul)
    if mm:
        rep.kv("AKT_FORG tartomany", "{0} .. {1}".format(
            mm[0].get("MN"), mm[0].get("MX")))
    if lim and tul:
        rep.verdict("Van LIMIT folotti koltes -> a LIMIT NEM kenyszerul ki "
                    "(vagy mast jelent).")
    elif lim:
        rep.verdict("Nincs LIMIT folotti koltes - lehet, hogy kikenyszerul, "
                    "de ez nem bizonyitek. Elo teszt kell.")

    # Hitelkeret (AKT_HITEL / LIMIT_HITEL): a feltetelezes az, hogy mar nem
    # hasznaljak. A VIP-ugynok ezekhez a mezokhoz nem kap jogot.
    rep.sub("Hitelkeret - hasznalja-e meg valaki?")
    hk, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS "
                   "WHERE LIMIT_HITEL > 0;")
    ha, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS "
                   "WHERE AKT_HITEL > 0.5 OR AKT_HITEL < -0.5;")
    tz, _ = db.num("SELECT COUNT(*) AS DB FROM KARTYATORZS WHERE TARTOZAS = 1;")
    hn, e = db.rows("SELECT COUNT(*) AS DB, MAX(DATUM) AS UTOLSO FROM "
                    "KARTYANAPLO WHERE TTIPUS IN ('HF', 'FH');",
                    ["DB", "UTOLSO"])
    rep.err(e)
    rep.kv("Kartya LIMIT_HITEL > 0", hk)
    rep.kv("Kartya AKT_HITEL <> 0", ha)
    rep.kv("Kartya TARTOZAS = 1", tz)
    hdb = hn[0].get("DB") if hn else None
    rep.kv("Hitelmozgas a naploban (HF/FH) / utolso",
           "{0} / {1}".format(hdb, (hn[0].get("UTOLSO") if hn else None) or "-"))
    if not hk and not ha and not tz:
        rep.verdict("Nincs elo hitelkeret es nincs tartozas - a hitelkeret "
                    "nincs hasznalatban. A dashboardon nem kell kezelni.")
    else:
        rep.verdict("Van elo hitelkeret vagy tartozas - meg kell beszelni, "
                    "mielott a dashboard barmit mutat vagy kezel belole.")

    for t in ("KARTYATIPUS", "KARTYAGYUJTO"):
        rep.sub(t + " (konfiguracio, teljes tartalom)")
        out, e = db.raw("SELECT * FROM {0};".format(t))
        rep.err(e)
        body = [mask_digits(l.rstrip()) for l in out.splitlines()
                if l.strip() and not l.strip().startswith(
                    ("SQL>", "CON>", "Database:"))]
        for l in body[:80]:
            rep.text(l)
        if len(body) > 80:
            rep.text("... ({0} sor tovabb)".format(len(body) - 80))

    rep.h("7. A 2026-09-06-I TESZTKARTYA (ID 610)")
    rows, e = db.rows(
        "SELECT ID, AKT_KP, LIMIT_KP, AKT_FORG, ERVENYES FROM KARTYATORZS "
        "WHERE ID = 610;", ["ID", "AKT_KP", "LIMIT_KP", "AKT_FORG", "ERVENYES"])
    rep.err(e)
    if rows:
        r = rows[0]
        rep.kv("Megvan", "AKT_KP={0}  LIMIT_KP={1}  AKT_FORG={2}  "
               "ERVENYES={3}".format(r.get("AKT_KP"), r.get("LIMIT_KP"),
                                     r.get("AKT_FORG"), r.get("ERVENYES")))
        nap, _ = db.rows("SELECT ID, TTIPUS, OSSZEG, AKT FROM KARTYANAPLO "
                         "WHERE KARTYA = 610 ORDER BY ID;",
                         ["ID", "TTIPUS", "OSSZEG", "AKT"])
        for n in nap:
            rep.text("naplo {0}: {1} {2} (elotte {3})".format(
                n.get("ID"), n.get("TTIPUS"), n.get("OSSZEG"), n.get("AKT")))
        rep.verdict("Meg el - takaritani kell, vagy tudatosan tesztkartyakent "
                    "megtartani. LIMIT_KP = AKT_KP = 20 azt jelenti, hogy a "
                    "javitott (ketutasitasos) feltoltes futott le rajta; "
                    "30/20 a regi, hibas valtozat nyoma lenne.")
    else:
        rep.kv("Megvan", "nem - mar torolve")


# ===========================================================================
# 8. Irasra keszules: triggerek, fuggosegek, jogok, generatorok
# ===========================================================================

WRITE_TABLES = ("KARTYATORZS", "KARTYANAPLO", "KARTYATULAJDONOS")


def sec_iras(db, rep):
    rep.h("8. IRASRA KESZULES: TRIGGEREK, FUGGOSEGEK, JOGOK")
    inlist = ", ".join("'{0}'".format(t) for t in WRITE_TABLES)
    rows, e = db.rows(
        "SELECT RDB$TRIGGER_NAME AS NEV, RDB$RELATION_NAME AS TABLA, "
        "RDB$TRIGGER_TYPE AS TIPUS, RDB$TRIGGER_INACTIVE AS INAKTIV "
        "FROM RDB$TRIGGERS WHERE RDB$RELATION_NAME IN ({0}) AND "
        "(RDB$SYSTEM_FLAG IS NULL OR RDB$SYSTEM_FLAG = 0);".format(inlist),
        ["NEV", "TABLA", "TIPUS", "INAKTIV"])
    rep.err(e)
    tipus = {"1": "BEFORE INSERT", "2": "AFTER INSERT", "3": "BEFORE UPDATE",
             "4": "AFTER UPDATE", "5": "BEFORE DELETE", "6": "AFTER DELETE"}
    triggers = []
    for r in rows:
        n = (r.get("NEV") or "").strip()
        triggers.append(n)
        rep.text("{0:<28} {1:<18} {2:<14} {3}".format(
            n, (r.get("TABLA") or "").strip(),
            tipus.get(r.get("TIPUS"), r.get("TIPUS")),
            "INAKTIV" if r.get("INAKTIV") == "1" else ""))

    # Mitol fuggenek ezek a triggerek (es egy szinttel lejjebb az
    # eljarasok)? Ebbol latszik, milyen GRANT kell a korlatozott
    # felhasznalonak, hogy az irasa ne szalljon el.
    rep.sub("Fuggosegek (trigger/eljaras -> objektum)")
    seen, queue = set(), [t for t in triggers if IDENT.match(t)]
    otype = {"0": "tabla", "1": "nezet", "2": "trigger", "5": "eljaras",
             "7": "kivetel", "14": "generator"}
    while queue and len(seen) < 40:
        batch = [q for q in queue if q not in seen]
        queue = []
        if not batch:
            break
        seen.update(batch)
        rows, e = db.rows(
            "SELECT DISTINCT RDB$DEPENDENT_NAME AS KI, RDB$DEPENDED_ON_NAME "
            "AS MIT, RDB$DEPENDED_ON_TYPE AS MT FROM RDB$DEPENDENCIES WHERE "
            "RDB$DEPENDENT_NAME IN ({0});".format(
                ", ".join("'{0}'".format(b) for b in batch)),
            ["KI", "MIT", "MT"])
        rep.err(e)
        for r in rows:
            ki, mit = (r.get("KI") or "").strip(), (r.get("MIT") or "").strip()
            rep.text("{0:<28} -> {1:<28} ({2})".format(
                ki, mit, otype.get(r.get("MT"), r.get("MT"))))
            if r.get("MT") == "5" and IDENT.match(mit):
                queue.append(mit)

    rep.sub("Oszlopszintu jog tamogatasa")
    n, e = db.num("SELECT COUNT(*) AS DB FROM RDB$RELATION_FIELDS WHERE "
                  "RDB$RELATION_NAME = 'RDB$USER_PRIVILEGES' AND "
                  "RDB$FIELD_NAME = 'RDB$FIELD_NAME';")
    rep.kv("RDB$USER_PRIVILEGES.RDB$FIELD_NAME letezik",
           "igen" if n else "NEM")

    rep.sub("Meglevo PEPPER_* jogok")
    rows, e = db.rows(
        "SELECT RDB$USER AS KI, RDB$RELATION_NAME AS MIT, RDB$PRIVILEGE AS "
        "JOG, RDB$FIELD_NAME AS MEZO FROM RDB$USER_PRIVILEGES WHERE "
        "RDB$USER STARTING WITH 'PEPPER' OR (RDB$USER_TYPE = 2 AND "
        "RDB$RELATION_NAME = 'KARTYATULAJDONOS');",
        ["KI", "MIT", "JOG", "MEZO"])
    if not rows:
        rep.text("nincs (a setup_users.py meg nem futott)")
    for r in rows:
        rep.text("{0:<20} {1:<4} {2:<24} {3}".format(
            (r.get("KI") or "").strip(), (r.get("JOG") or "").strip(),
            (r.get("MIT") or "").strip(), (r.get("MEZO") or "").strip()))

    rep.sub("Generatorok vs. MAX(ID)")
    for gen, tab in (("G_KARTYA", "KARTYATORZS"),
                     ("GEN_KARTYANAPLO", "KARTYANAPLO")):
        r, e = db.rows(
            "SELECT GEN_ID({0}, 0) AS G, (SELECT MAX(ID) FROM {1}) AS M "
            "FROM RDB$DATABASE;".format(gen, tab), ["G", "M"])
        if r:
            rep.kv("{0} / MAX({1}.ID)".format(gen, tab), "{0} / {1}".format(
                r[0].get("G"), r[0].get("M")))
        else:
            rep.err(e)


def sec_nevek(db, rep, kartyak):
    """Azonos nevu kartyak (pl. egy szemelyzeti es egy feltoltos). Nevet nem
    ir ki, csak kartya-ID-t es tipust."""
    rep.h("9. AZONOS NEVU KARTYAK")
    if kartyak is None:
        rows, e = db.rows("SELECT K.ID AS ID, K.TIPUS AS TIPUS, K.KARTYA AS "
                          "KOD, K.NEV AS NEV FROM KARTYATORZS K;",
                          ["ID", "TIPUS", "KOD", "NEV"])
        rep.err(e)
        kartyak = dict((_i(r.get("ID")), r) for r in rows)
    csop, kodok = {}, {}
    for kid, k in kartyak.items():
        nev = " ".join(_s(k.get("NEV")).split()).upper()
        if nev:
            csop.setdefault(nev, []).append((kid, _i(k.get("TIPUS"))))
        kod = _s(k.get("KOD")).strip()
        if kod:
            kodok[kod] = kodok.get(kod, 0) + 1
    tobb = [sorted(v) for v in csop.values() if len(v) > 1]
    rep.kv("Kartyak / kulonbozo nevek", "{0} / {1}".format(len(kartyak), len(csop)))
    rep.kv("Nevek, amelyek tobb kartyan szerepelnek", len(tobb))
    kombo = {}
    for g in tobb:
        k = "+".join(str(t) for _, t in sorted(g, key=lambda x: (x[1], x[0])))
        kombo[k] = kombo.get(k, 0) + 1
    for k in sorted(kombo):
        rep.kv("  tipusok: " + k, kombo[k])
    if tobb:
        rep.sub("Azonos nevu kartyak (kis-/nagybetu es szokoz nelkul; kartya-ID, tipus)")
        for g in tobb[:20]:
            rep.text(", ".join("ID {0} (tipus {1})".format(i, t) for i, t in g))
    rep.kv("Kartyakod, ami tobb kartyan is szerepel",
           sum(1 for n in kodok.values() if n > 1))

    rep.sub("Mezohosszak (KARTYATORZS)")
    rows, e = db.rows(
        "SELECT RF.RDB$FIELD_NAME AS MEZO, F.RDB$CHARACTER_LENGTH AS HOSSZ, "
        "F.RDB$FIELD_LENGTH AS BAJT, F.RDB$FIELD_TYPE AS FT FROM "
        "RDB$RELATION_FIELDS RF JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME = "
        "RF.RDB$FIELD_SOURCE WHERE RF.RDB$RELATION_NAME = 'KARTYATORZS' "
        "AND RF.RDB$FIELD_NAME IN ('NEV', 'KARTYA');",
        ["MEZO", "HOSSZ", "BAJT", "FT"])
    rep.err(e)
    ft = {"14": "CHAR", "37": "VARCHAR"}
    for r in rows:
        h = r.get("HOSSZ")
        rep.kv("  " + (r.get("MEZO") or "").strip(), "{0}({1})".format(
            ft.get(r.get("FT"), "tipus " + str(r.get("FT"))),
            h if h not in (None, "<null>") else r.get("BAJT")))
    hosszak = [len(" ".join(_s(k.get("NEV")).split())) for k in kartyak.values()]
    if hosszak:
        rep.kv("  Leghosszabb meglevo nev (karakter)", max(hosszak))
    rep.verdict("Az ugynok kartya-ID alapjan dolgozik, a nev nem azonosit. "
                "Az azonos nev csak a kijelzesnel szamit.")


def sec_forras(db, rep):
    """A kartya-modositaskor futo triggerek es eljarasok forrasa - igy
    latszik, mit ellenoriz pl. az NH$CHK_DBL_VIP_CARD."""
    rep.h("10. KARTYA-TRIGGEREK ES ELJARASOK FORRASA")
    rows, e = db.rows(
        "SELECT RDB$TRIGGER_NAME AS NEV FROM RDB$TRIGGERS WHERE "
        "RDB$RELATION_NAME IN ('KARTYATORZS', 'KARTYANAPLO');", ["NEV"])
    rep.err(e)
    triggerek = [n for n in ((r.get("NEV") or "").strip() for r in rows)
                 if IDENT.match(n) and not n.startswith("CHECK_")]
    rep.text("(A CHECK_* triggerek a CHECK-feltetelek rendszertriggerei, "
             "forrasuk nem kerheto le.)")
    eljarasok = ["NH$CHK_DBL_VIP_CARD"]
    if triggerek:
        rows, e = db.rows(
            "SELECT DISTINCT RDB$DEPENDED_ON_NAME AS MIT, RDB$DEPENDED_ON_TYPE "
            "AS MT FROM RDB$DEPENDENCIES WHERE RDB$DEPENDED_ON_TYPE = 5 AND "
            "RDB$DEPENDENT_NAME IN ({0});"
            .format(", ".join("'{0}'".format(t) for t in triggerek)),
            ["MIT", "MT"])
        rep.err(e)
        for r in rows:
            n = (r.get("MIT") or "").strip()
            if r.get("MT") == "5" and IDENT.match(n) and n not in eljarasok:
                eljarasok.append(n)
    for fajta, nevek in (("TRIGGER", sorted(triggerek)),
                         ("PROCEDURE", eljarasok)):
        for n in nevek:
            rep.sub("{0} {1}".format(fajta, n))
            out, err = db.raw("SHOW {0} {1};".format(fajta, n))
            sorok = [l.rstrip() for l in out.splitlines()
                     if l.strip() and not l.startswith("SQL>")]
            if not sorok:
                rep.text("(nincs kimenet)")
            for l in sorok[:200]:
                rep.text(l)
            if len(sorok) > 200:
                rep.text("... ({0} sor, levagva)".format(len(sorok)))
            rep.err(err)


# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="Csak olvaso felderites.")
    ap.add_argument("--user", choices=["olvas", "sysdba"],
                    help="alapbol PEPPER_OLVAS, ha van jelszava az ini-ben")
    ap.add_argument("--nyugtak", type=int, default=100000,
                    help="ennyi utolso nyugtat vizsgal (alap: 100000)")
    ap.add_argument("--kis-ablak", type=int, default=10000,
                    help="a reszletes (teteles) vizsgalat ablaka, nyugtaban "
                         "(alap: 10000)")
    args = ap.parse_args()

    cfg = load_config()
    user = args.user or ("olvas" if cfg.users["olvas"][1] else "sysdba")
    try:
        cfg.password(user)
    except ConfigError as e:
        sys.exit("HIBA: {0}\nMasold a pepper_agent.ini.example-t "
                 "pepper_agent.ini neven es toltsd ki.".format(e))
    tools_ok = bool(cfg.users["sysdba"][1])

    db = DB(cfg, user)
    # Elso lepes: egy proba-lekerdezes. Ha ez sem parszolhato, nem megyunk
    # tovabb - es megmutatjuk, mit adott vissza az isql.
    probe, err = db.one("SELECT 1 AS X FROM RDB$DATABASE;", "X")
    if probe != "1":
        sys.exit("HIBA: a proba-lekerdezes nem futott le.\n"
                 "stderr: {0}\nkimenet eleje:\n{1}".format(
                     (err or "").strip()[:300], db.last_out.strip()[:500]))

    rep = Report()
    rep.lines += ["PEPPER HOUSE - NOVOHOST FELDERITES (csak olvaso)",
                  "Felhasznalo: {0}   Verzio: {1}".format(cfg.user(user),
                                                         AGENT_VERSION),
                  "A jelentes nem tartalmaz nevet, kartyakodot vagy mas "
                  "szemelyes adatot."]

    db.progress("-- 0. kornyezet")
    sec_kornyezet(cfg, rep, tools_ok, db)

    db.progress("-- 1-2. fizetesek")
    mx, err = db.num("SELECT MAX(ID) AS MX FROM NYUGTAFEJ;", "MX")
    if mx is None:
        rep.h("NYUGTAFEJ nem olvashato - az 1-2. szakasz kimarad")
        rep.err(err)
    else:
        lo = max(0, mx - args.nyugtak)
        lo_kicsi = max(0, mx - args.kis_ablak)
        d = load_fizetesek(db, lo, lo_kicsi)
        sec_kkodid(d, rep, lo, lo_kicsi, args.nyugtak)
        sec_minta(d, rep)
        sec_reszfizetes(d, rep, db)
    db.progress("-- 3. EAN")
    sec_ean(db, rep)
    db.progress("-- 4. etlap")
    sec_etlap(db, rep)
    db.progress("-- 5-7. kartyak")
    sec_kartyak(db, rep)
    if mx is not None:
        sec_naplo_invarians(d, rep)
    db.progress("-- 8. iras")
    sec_iras(db, rep)
    db.progress("-- 9. azonos nevek")
    sec_nevek(db, rep, d["kartyak"] if mx is not None else None)
    db.progress("-- 10. forrasok")
    sec_forras(db, rep)
    db.progress("-- kesz")

    if db.errors:
        rep.h("ISQL HIBAK OSSZESITVE ({0})".format(len(db.errors)))
        for sql, err in db.errors:
            rep.text(sql)
            rep.text("  -> " + err.strip().splitlines()[0][:110])

    name = "felderites_{0}_{1}.txt".format(
        re.sub(r"[^A-Za-z0-9]+", "", cfg.helyszin or socket.gethostname()),
        time.strftime("%Y%m%d_%H%M"))
    path = os.path.join(HERE, name)
    # utf-8 BOM-mal: a regi Jegyzettomb enelkul rosszul mutatja.
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(str(rep))
    print(str(rep))
    print("Mentve: " + path)


if __name__ == "__main__":
    main()
