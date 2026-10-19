# -*- coding: utf-8 -*-
"""
jelentes.py - percenkenti eletjel a Pepper Adminnak (pepperadmin.zentopia.io).

Mit kuld (HTTPS, helyszin-tokennel):
  - helyszin, gep, ugynok-verzio, Python-verzio
  - a mentes allapota (mentes_allapot.json - mikor, mekkora, hiba)
  - adatbazis-proba: a PEPPER_OLVAS felhasznaloval a kartyanaplo
    generatoranak erteke (GEN_ID(..., 0) - tablat nem olvas, nem ir)
  - az utolso frissitesi kiserlet eredmenye

Feltoltos kartyak (kartyak.py): a mozgasok (kartya-ID, osszeg, idopont),
az egyenlegek es a kartyak neve (a szerveren titkositva). Kikapcsolhato:
[kartyak] kuldes = nem, illetve csak a nevek: nevek = nem.

Amit NEM kuld: kartyakodot, nyugtat, szemelyzeti kartyat.

Ha a valasz szerint ki van jelolve egy ujabb, alairt kiadas, atadja a
frissito.py-nak (ami az alairast es a verziot ellenorzi). Parancsot a
felho nem kuld; a gep csak jelent es frissul.

Gyakori figyeles: nyitvatartasban ([gyors] tol-ig, alap 6-21 ora) a futas
nem lep ki azonnal, hanem kb. 50 mp-ig 5 mp-enkent ranez a kartyanaplora,
es csak valtozaskor kuld. Igy egy kartyas fizetes nehany masodpercen belul
latszik az adminban. Ket futas sosem fut egyszerre (jelentes.lock).

FUTTATAS:
    python jelentes.py              egy jelentes (az utemezett feladat ezt hivja)
    python jelentes.py --proba      egy jelentes, a kuldott adattal es a valasszal
    python jelentes.py --titkosit   a token DPAPI-val titkositva az ini-be

Naplo: jelentes_log.txt - csak hibat es valtozast ir (nem percenkent egy
sort), es 512 KB felett atfordul.
"""

import argparse
import json
import os
import platform
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

from common import (AGENT_VERSION, HERE, INI_PATH, dpapi_protect, is_windows,
                    load_config, log, parse_list, run_isql, set_log)

LOG = os.path.join(HERE, "jelentes_log.txt")
MENTES = os.path.join(HERE, "mentes_allapot.json")
FRISSITES = os.path.join(HERE, "frissites_allapot.json")
UTOLSO = os.path.join(HERE, "jelentes_allapot.json")
GEP = os.path.join(HERE, "gep_allapot.json")
ZAR = os.path.join(HERE, "jelentes.lock")
FUTAS_MP = 50           # a percenkenti futas eddig figyel gyorsan, aztan kilep


def read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def rotate_log():
    try:
        if os.path.getsize(LOG) > 512 * 1024:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass


def db_proba(cfg):
    """Eleri-e a PEPPER_OLVAS az adatbazist? Csak generatort olvas."""
    if not cfg.users["olvas"][1]:
        return {"ok": False, "hiba": "nincs PEPPER_OLVAS jelszo az ini-ben"}
    try:
        out, err = run_isql(cfg, "SET LIST ON;\nSELECT GEN_ID(GEN_KARTYANAPLO, 0) "
                                 "AS G FROM RDB$DATABASE;", user_key="olvas")
        rows = parse_list(out, ["G"])
        if rows and rows[0].get("G"):
            return {"ok": True, "naplo_gen": int(float(rows[0]["G"]))}
        return {"ok": False, "hiba": (err or out).strip()[:200] or "ures valasz"}
    except Exception as e:
        return {"ok": False, "hiba": str(e)[:200]}


def payload(cfg):
    db = db_proba(cfg)
    d = {
        "helyszin": cfg.helyszin,
        "gep": socket.gethostname(),
        "agent_verzio": AGENT_VERSION,
        "python": platform.python_version(),
        "os": platform.platform()[:80],
        "ido": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": db,
        "mentes": read_json(MENTES) or {},
        "frissites": read_json(FRISSITES),
        # az elozo futas (kb. 1 perc) terhelese - lasd gepterheles.py
        # (kulon kulcs: a "gep" a gep neve)
        "terheles": _terheles(),
        # be van-e kapcsolva az iras ([iras] be = igen) - az admin ez alapjan
        # mutatja az egyenleg-modositast
        "iras_be": bool(cfg.iras["be"]),
    }
    try:
        import iras
        k = iras.kuldendo()
        if k:
            d["parancs_eredmeny"] = k
    except Exception as e:
        log("iras-eredmenyek olvasasa: {0}".format(e))
    # Feltoltos kartyak mozgasai (kartyak.py). Hiba eseten az eletjel
    # akkor is elmegy, a hiba pedig latszik az adminban.
    try:
        import kartyak
        d["kartyak"] = kartyak.gyujt(cfg, db.get("naplo_gen") if db.get("ok") else None)
    except Exception as e:
        d["kartyak"] = {"hiba": str(e)[:200]}
    return d


def ssl_context():
    """A rendszer tanusitvanyai + a mellekelt cacert.pem (friss Windowson a
    rendszer-tar hianyos lehet: CERTIFICATE_VERIFY_FAILED)."""
    ctx = ssl.create_default_context()
    ca = os.path.join(HERE, "cacert.pem")
    if os.path.exists(ca):
        try:
            ctx.load_verify_locations(cafile=ca)
        except Exception:
            pass
    return ctx


def post(url, token, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url + "/api/jelentes.php", data=body, headers={
        "Content-Type": "application/json",
        "X-Pepper-Token": token,
        "User-Agent": "PepperAgent/" + AGENT_VERSION,
    })
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:
            return json.loads(r.read(65536).decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read(4096).decode("utf-8"))
        except Exception:
            return {"ok": False, "hiba": "HTTP {0}".format(e.code)}


def tisztit_token(s):
    """Elfogadja az admin teljes 'token = ...' soranak bemasolasat is,
    szokozzel, sortoressel, idezojellel. Visszaad: (token vagy None, ok)."""
    s = s.strip().strip("﻿")
    m = re.match(r"(?i)^\s*token\s*[=:]\s*", s)
    if m:
        s = s[m.end():]
    s = re.sub(r"[\s\"']", "", s)
    if re.match(r"^[0-9a-fA-F]{64}$", s):
        return s.lower(), None
    hex_db = len(re.findall(r"[0-9a-fA-F]", s))
    ok = "{0} karaktert kaptam, ebbol {1} hexa (0-9, a-f).".format(len(s), hex_db)
    if any(ord(ch) < 32 for ch in s):
        ok += (" Vezerlokaraktert is kaptam: a rejtett bevitelnel a Ctrl+V nem "
               "illeszt be. Ird a tokent az ini [felho] szakaszaba 'token = ...' "
               "sorkent, es futtasd ujra a parancsot.")
    return None, ok


def _ini_olvas():
    with open(INI_PATH, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(enc), enc, raw.startswith(b"\xef\xbb\xbf")
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1", False


def _ini_token_sor(szoveg):
    """A [felho] szakasz nyilt 'token =' sora: (sorindex, ertek) vagy None."""
    szakasz = None
    for i, sor in enumerate(szoveg.splitlines()):
        s = sor.strip()
        if s.startswith("[") and s.endswith("]"):
            szakasz = s[1:-1].strip().lower()
        elif szakasz == "felho":
            m = re.match(r"(?i)^token\s*[=:]\s*(.*)$", s)
            if m and m.group(1).strip():
                return i, m.group(1).strip()
    return None


def _terheles():
    t = read_json(GEP)
    if isinstance(t, dict):
        t = dict((k, v) for k, v in t.items() if k != "nyers")
    return t


def zarol():
    """Egyszerre csak egy jelentes-futas. A 2 percnel regebbi zar elavult
    (pl. aramszunet utan maradt)."""
    try:
        if os.path.exists(ZAR) and time.time() - os.path.getmtime(ZAR) < 120:
            return False
        with open(ZAR, "w") as f:
            f.write(str(os.getpid()))
        return True
    except OSError:
        return False


def felold():
    try:
        os.remove(ZAR)
    except OSError:
        pass


def gyors_figyeles(cfg, url, token, t0, utolso_gen):
    """
    Nyitvatartasban a percenkenti futas nem lep ki azonnal: FUTAS_MP-ig
    utem masodpercenkent megnezi a kartyanaplo generatorat (egy apro
    lekerdezes), es csak valtozaskor kuld - a mozgast, az uj egyenleget es
    a vasarolt teteleket. Uj utemezett feladat nem kell hozza.
    """
    g = cfg.gyors
    ora = int(time.strftime("%H"))
    if not g["be"] or not cfg.kartyak["kuldes"] or not (g["tol"] <= ora < g["ig"]):
        return
    import kartyak
    while time.time() - t0 + g["utem"] < FUTAS_MP:
        time.sleep(g["utem"])
        db = db_proba(cfg)
        gen = db.get("naplo_gen") if db.get("ok") else None
        if gen is None or gen == utolso_gen:
            continue
        try:
            ki = kartyak.gyujt(cfg, gen)
            if not ki:
                return
            resp = post(url, token, {
                "helyszin": cfg.helyszin, "agent_verzio": AGENT_VERSION,
                "gyors": True, "ido": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kartyak": ki})
            kartyak.nyugtaz(ki, resp)
            if resp.get("ok"):
                utolso_gen = gen
        except Exception as e:
            log("gyors figyeles hiba: {0}".format(str(e)[:200]))
            return


def cmd_titkosit():
    """A token DPAPI-val. Ha az ini [felho] szakaszaban van nyilt 'token ='
    sor, azt titkositja es a helyere irja (nem kell bemasolni semmit);
    kulonben bekeri."""
    if not is_windows():
        sys.exit("A DPAPI csak Windows-on erheto el.")
    talalat = None
    if os.path.exists(INI_PATH):
        szoveg, enc, bom = _ini_olvas()
        talalat = _ini_token_sor(szoveg)
    if talalat:
        idx, ertek = talalat
        t, ok = tisztit_token(ertek)
        if not t:
            sys.exit("A pepper_agent.ini 'token =' soraban nem 64 jegyu hexa token "
                     "van. " + ok)
        sorok = szoveg.splitlines(True)
        veg = "\r\n" if sorok[idx].endswith("\r\n") else "\n"
        sorok[idx] = "token_dpapi = {0}{1}".format(dpapi_protect(t), veg)
        # Az esetleges ures 'token_dpapi =' sablonsor felesleges.
        uj = [s for j, s in enumerate(sorok)
              if j == idx or not re.match(r"(?i)^\s*token_dpapi\s*[=:]\s*$", s)]
        adat = "".join(uj).encode(enc if enc != "utf-8-sig" else "utf-8")
        if bom:
            adat = b"\xef\xbb\xbf" + adat
        with open(INI_PATH, "wb") as f:
            f.write(adat)
        print("Kesz: a pepper_agent.ini-ben a nyilt token helyen most mar "
              "'token_dpapi = ...' all.")
        print("Ellenorzes: python jelentes.py --proba")
        return

    import getpass
    print("Tipp: egyszerubb, ha a pepper_agent.ini [felho] szakaszaba beirod a\n"
          "'token = ...' sort, es ugy futtatod ujra ezt a parancsot.\n")
    t, ok = tisztit_token(getpass.getpass(
        "Token (nem jelenik meg; jobb egergombbal illeszd be): "))
    if not t:
        sys.exit("Ez nem 64 jegyu hexa token. " + ok)
    print("\ntoken_dpapi = {0}\n".format(dpapi_protect(t)))
    print("Ezt a sort tedd a pepper_agent.ini [felho] szakaszaba, a nyilt "
          "'token =' sort pedig torold.")


def main():
    ap = argparse.ArgumentParser(description="Eletjel a Pepper Adminnak.")
    ap.add_argument("--proba", action="store_true",
                    help="kiirja a kuldott adatot es a valaszt")
    ap.add_argument("--titkosit", action="store_true",
                    help="a token DPAPI-val titkositva az ini-be")
    args = ap.parse_args()
    if args.titkosit:
        cmd_titkosit()
        return

    rotate_log()
    set_log(LOG)
    cfg = load_config()
    url, token = cfg.felho["url"], cfg.felho["token"]
    if not url or not token or not cfg.helyszin:
        sys.exit("HIBA: a pepper_agent.ini-ben kell [general] helyszin, es "
                 "[felho] url + token (vagy token_dpapi).")

    if not args.proba and not zarol():
        return      # elozo futas meg tart - a feladat percenkent ujra indul
    t0 = time.time()
    try:
        import gepterheles
        meres = gepterheles.Meres((read_json(GEP) or {}).get("nyers"))
    except Exception:
        meres = None
    try:
        kod = futas(cfg, url, token, args, t0)
    finally:
        if meres is not None:
            try:
                eredm = meres.eredmeny()
                if eredm:
                    with open(GEP, "w", encoding="utf-8") as f:
                        json.dump(eredm, f)
            except Exception:
                pass
        if not args.proba:
            felold()
    sys.exit(kod)


def futas(cfg, url, token, args, t0):
    data = payload(cfg)
    if args.proba:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    try:
        resp = post(url, token, data)
    except Exception as e:
        resp = {"ok": False, "hiba": "kapcsolodasi hiba: {0}".format(e)}
    if args.proba:
        print("\nValasz:", json.dumps(resp, ensure_ascii=False))
    try:
        import iras
        iras.nyugtaz(resp)
        if resp.get("ok") and resp.get("parancsok"):
            # Az admin utasitasai: vegrehajtas, es az eredmeny azonnal fel.
            iras.vegrehajt(cfg, resp["parancsok"])
            r2 = post(url, token, {
                "helyszin": cfg.helyszin, "agent_verzio": AGENT_VERSION,
                "gyors": True, "ido": time.strftime("%Y-%m-%d %H:%M:%S"),
                "parancs_eredmeny": iras.kuldendo()})
            iras.nyugtaz(r2)
    except Exception as e:
        log("iras hiba: {0}".format(str(e)[:200]))

    ki = data.get("kartyak")
    if ki and "hiba" not in ki:
        try:
            import kartyak
            kartyak.nyugtaz(ki, resp)
        except Exception as e:
            log("kartya-kurzor mentese nem sikerult: {0}".format(e))

    # Csak valtozast naplozunk: ok -> hiba, hiba -> ok, vagy uj hibaszoveg.
    elozo = read_json(UTOLSO) or {}
    allapot = "ok" if resp.get("ok") else "hiba: " + str(resp.get("hiba"))[:200]
    if allapot != elozo.get("allapot") or args.proba:
        log("jelentes {0} (verzio {1})".format(allapot, AGENT_VERSION))
    try:
        with open(UTOLSO, "w", encoding="utf-8") as f:
            json.dump({"ido": data["ido"], "allapot": allapot}, f)
    except OSError:
        pass

    fr = resp.get("frissites") if resp.get("ok") else None
    if fr:
        import frissito
        log("Frissites kijelolve: {0} -> {1}".format(AGENT_VERSION,
                                                    fr.get("verzio")))
        eredmeny = frissito.frissit(url, token, fr, AGENT_VERSION)
        log("Frissites: " + eredmeny)
        if args.proba:
            print("Frissites:", eredmeny)
        return 0 if resp.get("ok") else 1   # uj kod: a kovetkezo futas figyel

    if resp.get("ok") and not args.proba:
        db = data.get("db") or {}
        gyors_figyeles(cfg, url, token, t0, db.get("naplo_gen"))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    main()
