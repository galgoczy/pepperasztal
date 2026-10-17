# -*- coding: utf-8 -*-
"""
backup.py - a NovoHost adatbazis mentese, es a mentes ellenorzese MASIK gepen.

MIERT KULON SCRIPT, ES MIERT SYSDBA?
  InterBase 6-on a gbak mentest csak a SYSDBA vagy az adatbazis tulajdonosa
  futtathatja - a korlatozott PEPPER_* felhasznalok nem. Ezert ez egy kulon
  utemezett feladat, a VIP-ugynoktol fuggetlenul. A SYSDBA jelszo a helyi
  pepper_agent.ini-bol jon (DPAPI-val titkositva), kornyezeti valtozon at
  adjuk at a gbak-nak, sosem parancssoron.

MENTES (a POS gepen, naponta - install_backup.bat):
  1. ellenorzi a szabad helyet (legalabb a DB meretenek 2x-ese)
  2. MANIFEST: par darabszam a mentes pillanatabol (kartyak szama, utolso
     naplo- es nyugta-ID). Ezzel bizonyithato kesobb, hogy a mentes TELJES.
  3. gbak -b -g: mentes futas kozben, a kassza nem all meg. A -g kikapcsolja
     a mentes alatti szemetgyujtest - kevesebb terheles az eles szerveren.
  4. tomorit: .gbk + manifest egy archivumba (zip, vagy 7-Zip AES-256)
  5. rotacio: napi_db napi + heti_db heti mentes marad
  6. masolat a masolat_mappa-ba, ha be van allitva
  7. allapotfajl: mentes_allapot.json - mikor sikerult utoljara

PROBA-VISSZAALLITAS (--proba ARCHIV, egy MASIK gepen, ahol InterBase fut):
  Az eles POS gepen NEM fut - ha ott a NovoHost adatbazisa, megtagadja.
  Az archivumot visszaallitja egy atmeneti fajlba (gbak -c), a manifesttel
  osszeveti, majd torli. Ha a visszaallitott adatbazis legalabb annyi
  kartyat, naplosort es nyugtat tartalmaz, mint a manifest, a mentes teljes.
  A soha ki nem probalt mentes csak remeny.

FONTOS KORLAT:
  A teljes visszaallitas az eles POS-on a forgalmat is visszavinne a mentes
  allapotaba - ez csak katasztrofanal jarhato ut (halott lemez, serult DB),
  es kezzel csinaljuk. VIP-hiba javitasara a naplokbol szamolunk ujra.

FUTTATAS:
    python backup.py                         napi mentes (POS gep)
    python backup.py --proba ARCHIV.zip      ellenorzes (teszt gep)
"""

import argparse
import copy
import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

from common import (HERE, ConfigError, is_windows, load_config, log,
                    parse_list, run_isql, run_tool, set_log)

ALLAPOT = os.path.join(HERE, "mentes_allapot.json")
PREFIX = "novohost_"
MANIFEST_COLS = ["KARTYA", "NAPLO", "NYUGTA"]
MANIFEST_SQL = (
    "SET LIST ON;\n"
    "SELECT (SELECT COUNT(*) FROM KARTYATORZS) AS KARTYA,"
    " (SELECT MAX(ID) FROM KARTYANAPLO) AS NAPLO,"
    " (SELECT MAX(ID) FROM NYUGTAFEJ) AS NYUGTA FROM RDB$DATABASE;")


def gbak_exe():
    return "gbak.exe" if is_windows() else "gbak"


def archiv_ext(cfg):
    return ".7z" if cfg.backup["sevenzip"] else ".zip"


def tag(cfg):
    return re.sub(r"[^A-Za-z0-9]+", "", cfg.helyszin or socket.gethostname())


def mb(n):
    return n / 1048576.0


# ===========================================================================
# Allapot
# ===========================================================================

def save_state(**kw):
    st = {}
    if os.path.exists(ALLAPOT):
        try:
            with open(ALLAPOT, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
    st.update(kw)
    with open(ALLAPOT, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)


# ===========================================================================
# Tomorites
# ===========================================================================

def pack(cfg, srcs, dst):
    sz = cfg.backup["sevenzip"]
    if sz:
        pw = cfg.backup["archiv_jelszo"]
        if not pw:
            raise ConfigError("[backup] sevenzip be van allitva, de nincs "
                              "archiv-jelszo (password / password_dpapi).")
        rc = subprocess.call([sz, "a", "-t7z", "-mx=5", "-mhe=on",
                              "-p" + pw, dst] + list(srcs),
                             stdout=subprocess.DEVNULL)
        if rc != 0:
            raise RuntimeError("7-Zip hiba, kod {0}".format(rc))
        rc = subprocess.call([sz, "t", "-p" + pw, dst],
                             stdout=subprocess.DEVNULL)
        if rc != 0:
            raise RuntimeError("7-Zip teszt hibas, kod {0}".format(rc))
    else:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as z:
            for s in srcs:
                z.write(s, os.path.basename(s))
        with zipfile.ZipFile(dst) as z:
            bad = z.testzip()
        if bad is not None:
            raise RuntimeError("A zip serult: " + bad)


def unpack(cfg, src, dst_dir):
    """Visszaad: (gbk utvonal, manifest dict vagy None)"""
    if src.lower().endswith(".7z"):
        sz = cfg.backup["sevenzip"]
        if not sz:
            raise ConfigError("7z archivum, de nincs [backup] sevenzip.")
        rc = subprocess.call([sz, "e", "-y", "-p" + (cfg.backup[
            "archiv_jelszo"] or ""), "-o" + dst_dir, src],
            stdout=subprocess.DEVNULL)
        if rc != 0:
            raise RuntimeError("7-Zip kibontas hiba, kod {0} (jo a "
                               "jelszo?)".format(rc))
    else:
        with zipfile.ZipFile(src) as z:
            z.extractall(dst_dir)
    gbks = glob.glob(os.path.join(dst_dir, "*.gbk"))
    if not gbks:
        raise RuntimeError("Az archivumban nincs .gbk fajl.")
    man = None
    jsons = glob.glob(os.path.join(dst_dir, "*.json"))
    if jsons:
        with open(jsons[0], encoding="utf-8") as f:
            man = json.load(f)
    return gbks[0], man


# ===========================================================================
# Rotacio
# ===========================================================================

def archives(folder):
    files = []
    for e in (".zip", ".7z"):
        files += glob.glob(os.path.join(folder, PREFIX + "*" + e))
    return sorted(files, key=os.path.getmtime, reverse=True)


def prune(folder, keep):
    for f in archives(folder)[keep:]:
        try:
            os.remove(f)
            log("   torolve (rotacio): " + os.path.basename(f))
        except OSError as e:
            log("   nem torolheto: {0} ({1})".format(f, e))


def rotate(cfg, new_file):
    napi = os.path.join(cfg.backup["mappa"], "napi")
    heti = os.path.join(cfg.backup["mappa"], "heti")
    for d in (napi, heti):
        if not os.path.isdir(d):
            os.makedirs(d)
    # Heti: ha az elmult 6 napban nem keszult heti peldany, ez lesz az.
    recent = [f for f in archives(heti)
              if time.time() - os.path.getmtime(f) < 6 * 86400]
    if not recent:
        shutil.copy2(new_file, heti)
        log("   heti peldany: " + os.path.basename(new_file))
    prune(napi, cfg.backup["napi_db"])
    prune(heti, cfg.backup["heti_db"])


# ===========================================================================
# Mentes
# ===========================================================================

def read_counts(cfg):
    """A manifest szamai. READ ONLY tranzakcio, csak olvas."""
    out, err = run_isql(cfg, "SET TRANSACTION READ ONLY;\n" + MANIFEST_SQL,
                        user_key="sysdba")
    rows = parse_list(out, MANIFEST_COLS)
    if not rows or not rows[0].get("NYUGTA"):
        raise RuntimeError("A darabszamok nem olvashatok: " +
                           (err or out).strip()[:300])
    return dict((k, int(float(rows[0][k] or 0))) for k in MANIFEST_COLS)


def cmd_mentes(cfg):
    cfg.password("sysdba")
    napi = os.path.join(cfg.backup["mappa"], "napi")
    if not os.path.isdir(napi):
        os.makedirs(napi)
    if not os.path.exists(cfg.db_path):
        raise RuntimeError("Nem talalom az adatbazist: " + cfg.db_path)

    db_size = os.path.getsize(cfg.db_path)
    free = shutil.disk_usage(napi).free
    log("DB: {0:.0f} MB, szabad hely: {1:.0f} MB".format(mb(db_size),
                                                         mb(free)))
    if free < 2 * db_size:
        raise RuntimeError("Keves a hely: legalabb {0:.0f} MB kell.".format(
            mb(2 * db_size)))

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = "{0}{1}_{2}".format(PREFIX, tag(cfg), stamp)
    gbk = os.path.join(napi, base + ".gbk")
    man_path = os.path.join(napi, base + ".json")
    arch = os.path.join(napi, base + archiv_ext(cfg))

    log("1. manifest (darabszamok a mentes elott)")
    counts = read_counts(cfg)
    log("   kartya: {KARTYA}, utolso naplo ID: {NAPLO}, utolso nyugta ID: "
        "{NYUGTA}".format(**counts))

    log("2. gbak mentes -> " + os.path.basename(gbk))
    t0 = time.time()
    rc, out, err = run_tool(cfg, gbak_exe(), [
        "-b", "-g", "localhost:" + cfg.db_path, gbk])
    if rc != 0 or err.strip() or not os.path.exists(gbk) \
            or os.path.getsize(gbk) == 0:
        if os.path.exists(gbk):
            os.remove(gbk)
        raise RuntimeError("gbak hiba (kod {0}): {1}".format(
            rc, (err or out).strip()[:300]))
    gbk_size = os.path.getsize(gbk)
    log("   kesz, {0:.1f} MB, {1:.0f} mp".format(mb(gbk_size),
                                                 time.time() - t0))

    manifest = {
        "helyszin": cfg.helyszin, "gep": socket.gethostname(),
        "mentes_kezdete": stamp, "db_meret_mb": round(mb(db_size), 1),
        "gbk_meret_mb": round(mb(gbk_size), 1), "darabszamok": counts,
        "megjegyzes": "A darabszamok a gbak INDITASA ELOTT keszultek. A "
                      "visszaallitott DB-ben legalabb ennyi kell legyen.",
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    log("3. tomorites -> " + os.path.basename(arch))
    try:
        pack(cfg, [gbk, man_path], arch)
    finally:
        for p in (gbk, man_path):
            if os.path.exists(p):
                os.remove(p)
    arch_size = os.path.getsize(arch)
    log("   kesz, {0:.1f} MB".format(mb(arch_size)))

    log("4. rotacio")
    rotate(cfg, arch)

    masolat_ok = None
    dst = cfg.backup["masolat_mappa"]
    if dst:
        log("5. masolat -> " + dst)
        try:
            if not os.path.isdir(dst):
                os.makedirs(dst)
            shutil.copy2(arch, dst)
            prune(dst, cfg.backup["napi_db"] + cfg.backup["heti_db"])
            masolat_ok = True
            log("   kesz")
        except Exception as e:
            masolat_ok = False
            log("   HIBA: a kulso masolat nem sikerult: {0}".format(e))

    save_state(utolso_mentes=time.strftime("%Y-%m-%d %H:%M:%S"),
               utolso_fajl=os.path.basename(arch),
               db_meret_mb=round(mb(db_size), 1),
               gbk_meret_mb=round(mb(gbk_size), 1),
               archiv_meret_mb=round(mb(arch_size), 1),
               darabszamok=counts, masolat_ok=masolat_ok, utolso_hiba=None,
               mentesek={
                   "napi": [os.path.basename(f) for f in archives(napi)],
                   "heti": [os.path.basename(f) for f in archives(
                       os.path.join(cfg.backup["mappa"], "heti"))]})
    if masolat_ok is False:
        sys.exit(3)


# ===========================================================================
# Proba-visszaallitas (MASIK gepen)
# ===========================================================================

def cmd_proba(cfg, src, sajat_gepen):
    cfg.password("sysdba")
    if os.path.exists(cfg.db_path) and not sajat_gepen:
        raise RuntimeError(
            "Ez eles POS gepnek latszik (itt van a NovoHost adatbazisa: "
            "{0}). A proba-visszaallitas egy MASIK gepre valo. Ha tudod, mit "
            "csinalsz: --ezen-a-gepen".format(cfg.db_path))
    if not os.path.isfile(src):
        raise RuntimeError("Nincs ilyen archivum: " + src)
    log("Proba-visszaallitas: " + os.path.basename(src))

    root = cfg.backup["mappa"]
    if not os.path.isdir(root):
        os.makedirs(root)
    work = tempfile.mkdtemp(prefix="pepper_proba_", dir=root)
    try:
        gbk, man = unpack(cfg, src, work)
        need = 3 * os.path.getsize(gbk)
        if shutil.disk_usage(work).free < need:
            raise RuntimeError("Keves a hely: legalabb {0:.0f} MB "
                               "kell.".format(mb(need)))
        target = os.path.join(work, "proba.ib")
        t0 = time.time()
        rc, out, err = run_tool(cfg, gbak_exe(), [
            "-c", gbk, "localhost:" + target])
        if rc != 0 or not os.path.exists(target):
            raise RuntimeError("gbak -c hiba (kod {0}): {1}".format(
                rc, (err or out).strip()[:300]))
        log("   visszaallitva: {0:.1f} MB gbk -> {1:.0f} MB adatbazis, "
            "{2:.0f} mp".format(mb(os.path.getsize(gbk)),
                                mb(os.path.getsize(target)),
                                time.time() - t0))

        pcfg = copy.deepcopy(cfg)
        pcfg.db_path = target
        out, err = run_isql(pcfg, MANIFEST_SQL, user_key="sysdba")
        rows = parse_list(out, MANIFEST_COLS)
        if not rows or not rows[0].get("NYUGTA"):
            raise RuntimeError("A visszaallitott DB nem olvashato: " +
                               (err or out).strip()[:300])
        got = dict((k, int(float(rows[0][k] or 0))) for k in MANIFEST_COLS)
        log("   visszaallitott: kartya {KARTYA}, naplo ID {NAPLO}, "
            "nyugta ID {NYUGTA}".format(**got))

        if not man:
            log("   FIGYELEM: az archivumban nincs manifest (regi mentes) - "
                "csak az olvashatosagot igazoltuk, a teljesseget nem.")
            ok = True
        else:
            want = man["darabszamok"]
            log("   manifest:     kartya {KARTYA}, naplo ID {NAPLO}, "
                "nyugta ID {NYUGTA}".format(**want))
            hiany = [k for k in MANIFEST_COLS if got[k] < want[k]]
            ok = not hiany
            if hiany:
                log("   HIBA: a visszaallitott DB-bol hianyzik adat: " +
                    ", ".join(hiany))
        save_state(utolso_proba=time.strftime("%Y-%m-%d %H:%M:%S"),
                   utolso_proba_fajl=os.path.basename(src),
                   utolso_proba_ok=ok)
        log("A mentes TELJES es visszaallithato." if ok else
            "A MENTES NEM TELJES.")
        if not ok:
            sys.exit(4)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="NovoHost mentes.")
    ap.add_argument("--proba", metavar="ARCHIV",
                    help="proba-visszaallitas ebbol az archivumbol "
                         "(MASIK gepen)")
    ap.add_argument("--ezen-a-gepen", action="store_true",
                    help="a probat akkor is engedi, ha ez POS gepnek latszik")
    args = ap.parse_args()
    set_log(os.path.join(HERE, "mentes_log.txt"))
    cfg = load_config()
    try:
        if args.proba:
            cmd_proba(cfg, args.proba, args.ezen_a_gepen)
        else:
            cmd_mentes(cfg)
    except Exception as e:
        log("HIBA: {0}".format(e))
        if args.proba:
            save_state(utolso_proba=time.strftime("%Y-%m-%d %H:%M:%S"),
                       utolso_proba_ok=False, utolso_proba_hiba=str(e))
        else:
            save_state(utolso_hiba="{0} {1}".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), e))
        sys.exit(2)


if __name__ == "__main__":
    main()
