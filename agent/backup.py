# -*- coding: utf-8 -*-
"""
backup.py - a NovoHost adatbazis mentese, rotacioval es proba-visszaallitassal.

MIERT KULON SCRIPT, ES MIERT SYSDBA?
  InterBase 6-on a gbak mentest csak a SYSDBA vagy az adatbazis tulajdonosa
  futtathatja - a korlatozott PEPPER_* felhasznalok nem. Ezert ez egy kulon
  utemezett feladat, a VIP-ugynoktol fuggetlenul. A SYSDBA jelszo a helyi
  pepper_agent.ini-bol jon (DPAPI-val titkositva), kornyezeti valtozon at
  adjuk at a gbak-nak, sosem parancssoron.

MIT CSINAL (alap futas, naponta):
  1. ellenorzi a szabad helyet (legalabb a DB meretenek 2x-ese)
  2. gbak -b -g: mentes futas kozben, a kassza nem all meg. A -g kikapcsolja
     a mentes alatti szemetgyujtest - kevesebb terheles az eles szerveren.
  3. tomorit (zip, vagy 7-Zip AES-256 titkositassal, ha be van allitva)
  4. rotacio: napi_db napi + heti_db heti mentes marad
  5. masolat a masolat_mappa-ba (NAS, masik gep, felhos szinkron mappa)
  6. allapotfajl: mentes_allapot.json - mikor sikerult utoljara

PROBA-VISSZAALLITAS (--proba, hetente):
  A legujabb mentest visszaallitja egy ATMENETI fajlba (gbak -c), belenez,
  majd torli. Az eles adatbazishoz nem nyul. A soha ki nem probalt mentes
  csak remeny.

FONTOS KORLAT:
  A teljes visszaallitas az eles POS-on a forgalmat is visszavinne a mentes
  allapotaba - ez csak katasztrofanal jarhato ut (halott lemez, serult DB).
  VIP-hiba javitasara a naplokbol szamolunk ujra, nem mentesbol.

FUTTATAS:
    python backup.py            napi mentes
    python backup.py --proba    proba-visszaallitas a legujabb mentesbol
"""

import argparse
import copy
import datetime
import glob
import json
import os
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


def gbak_exe():
    return "gbak.exe" if is_windows() else "gbak"


def archiv_ext(cfg):
    return ".7z" if cfg.backup["sevenzip"] else ".zip"


def tag(cfg):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "", cfg.helyszin or socket.gethostname())


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

def pack(cfg, src, dst):
    sz = cfg.backup["sevenzip"]
    if sz:
        pw = cfg.backup["archiv_jelszo"]
        if not pw:
            raise ConfigError("[backup] sevenzip be van allitva, de nincs "
                              "archiv-jelszo (password / password_dpapi).")
        rc = subprocess.call([sz, "a", "-t7z", "-mx=5", "-mhe=on",
                              "-p" + pw, dst, src],
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
            z.write(src, os.path.basename(src))
        with zipfile.ZipFile(dst) as z:
            bad = z.testzip()
        if bad is not None:
            raise RuntimeError("A zip serult: " + bad)


def unpack(cfg, src, dst_dir):
    sz = cfg.backup["sevenzip"]
    if src.endswith(".7z"):
        if not sz:
            raise ConfigError("7z mentes, de nincs [backup] sevenzip utvonal.")
        rc = subprocess.call([sz, "e", "-y", "-p" + (cfg.backup[
            "archiv_jelszo"] or ""), "-o" + dst_dir, src],
            stdout=subprocess.DEVNULL)
        if rc != 0:
            raise RuntimeError("7-Zip kibontas hiba, kod {0}".format(rc))
    else:
        with zipfile.ZipFile(src) as z:
            z.extractall(dst_dir)
    found = glob.glob(os.path.join(dst_dir, "*.gbk"))
    if not found:
        raise RuntimeError("Az archivumban nincs .gbk fajl.")
    return found[0]


# ===========================================================================
# Rotacio
# ===========================================================================

def archives(folder):
    pats = [os.path.join(folder, PREFIX + "*" + e) for e in (".zip", ".7z")]
    files = []
    for p in pats:
        files += glob.glob(p)
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

def cmd_mentes(cfg):
    cfg.password("sysdba")
    napi = os.path.join(cfg.backup["mappa"], "napi")
    if not os.path.isdir(napi):
        os.makedirs(napi)
    if not os.path.exists(cfg.db_path):
        raise RuntimeError("Nem talalom az adatbazist: " + cfg.db_path)

    db_size = os.path.getsize(cfg.db_path)
    free = shutil.disk_usage(napi).free
    log("DB: {0:.0f} MB, szabad hely: {1:.0f} MB".format(
        db_size / 1048576.0, free / 1048576.0))
    if free < 2 * db_size:
        raise RuntimeError("Keves a hely: legalabb {0:.0f} MB kell.".format(
            2 * db_size / 1048576.0))

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = "{0}{1}_{2}".format(PREFIX, tag(cfg), stamp)
    gbk = os.path.join(napi, base + ".gbk")
    arch = os.path.join(napi, base + archiv_ext(cfg))

    log("1. gbak mentes -> " + os.path.basename(gbk))
    t0 = time.time()
    rc, out, err = run_tool(cfg, gbak_exe(), [
        "-b", "-g", "localhost:" + cfg.db_path, gbk])
    if rc != 0 or err.strip() or not os.path.exists(gbk) \
            or os.path.getsize(gbk) == 0:
        if os.path.exists(gbk):
            os.remove(gbk)
        raise RuntimeError("gbak hiba (kod {0}): {1}".format(
            rc, (err or out).strip()[:300]))
    log("   kesz, {0:.0f} MB, {1:.0f} mp".format(
        os.path.getsize(gbk) / 1048576.0, time.time() - t0))

    log("2. tomorites -> " + os.path.basename(arch))
    try:
        pack(cfg, gbk, arch)
    finally:
        if os.path.exists(gbk):
            os.remove(gbk)
    arch_size = os.path.getsize(arch)
    log("   kesz, {0:.1f} MB".format(arch_size / 1048576.0))

    log("3. rotacio")
    rotate(cfg, arch)

    masolat_ok = None
    dst = cfg.backup["masolat_mappa"]
    if dst:
        log("4. masolat -> " + dst)
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
    else:
        log("4. masolat: nincs beallitva [backup] masolat_mappa - a mentes "
            "csak ezen a gepen van!")

    save_state(utolso_mentes=time.strftime("%Y-%m-%d %H:%M:%S"),
               utolso_fajl=os.path.basename(arch),
               utolso_meret_mb=round(arch_size / 1048576.0, 1),
               masolat_ok=masolat_ok, utolso_hiba=None)
    if masolat_ok is False:
        sys.exit(3)


# ===========================================================================
# Proba-visszaallitas
# ===========================================================================

def cmd_proba(cfg):
    cfg.password("sysdba")
    napi = os.path.join(cfg.backup["mappa"], "napi")
    arcs = archives(napi)
    if not arcs:
        raise RuntimeError("Nincs mentes a(z) {0} mappaban.".format(napi))
    src = arcs[0]
    log("Proba-visszaallitas: " + os.path.basename(src))

    work = tempfile.mkdtemp(prefix="pepper_proba_", dir=cfg.backup["mappa"])
    try:
        gbk = unpack(cfg, src, work)
        need = 3 * os.path.getsize(gbk)
        if shutil.disk_usage(work).free < need:
            raise RuntimeError("Keves a hely a proba-visszaallitashoz.")
        target = os.path.join(work, "proba.ib")
        t0 = time.time()
        rc, out, err = run_tool(cfg, gbak_exe(), [
            "-c", gbk, "localhost:" + target])
        if rc != 0 or not os.path.exists(target):
            raise RuntimeError("gbak -c hiba (kod {0}): {1}".format(
                rc, (err or out).strip()[:300]))
        log("   visszaallitva, {0:.0f} MB, {1:.0f} mp".format(
            os.path.getsize(target) / 1048576.0, time.time() - t0))

        # Belenezunk: a fontos tablak olvashatok es nem uresek.
        pcfg = copy.deepcopy(cfg)
        pcfg.db_path = target
        out, err = run_isql(pcfg, (
            "SET LIST ON;\n"
            "SELECT (SELECT COUNT(*) FROM KARTYATORZS) AS KARTYA,"
            " (SELECT MAX(ID) FROM KARTYANAPLO) AS NAPLO,"
            " (SELECT MAX(ID) FROM NYUGTAFEJ) AS NYUGTA FROM RDB$DATABASE;"),
            user_key="sysdba")
        rows = parse_list(out, ["KARTYA", "NAPLO", "NYUGTA"])
        if err or not rows or not rows[0].get("NYUGTA"):
            raise RuntimeError("A visszaallitott DB nem olvashato: " +
                               (err or out)[:300])
        r = rows[0]
        log("   kartya: {0}, utolso naplo ID: {1}, utolso nyugta ID: {2}"
            .format(r.get("KARTYA"), r.get("NAPLO"), r.get("NYUGTA")))
        save_state(utolso_proba=time.strftime("%Y-%m-%d %H:%M:%S"),
                   utolso_proba_fajl=os.path.basename(src),
                   utolso_proba_ok=True)
        log("A mentes visszaallithato.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="NovoHost mentes.")
    ap.add_argument("--proba", action="store_true",
                    help="proba-visszaallitas a legujabb mentesbol")
    args = ap.parse_args()
    set_log(os.path.join(HERE, "mentes_log.txt"))
    cfg = load_config()
    try:
        if args.proba:
            cmd_proba(cfg)
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
