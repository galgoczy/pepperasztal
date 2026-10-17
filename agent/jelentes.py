# -*- coding: utf-8 -*-
"""
jelentes.py - percenkenti eletjel a Pepper Adminnak (pepperadmin.zentopia.io).

Mit kuld (HTTPS, helyszin-tokennel):
  - helyszin, gep, ugynok-verzio, Python-verzio
  - a mentes allapota (mentes_allapot.json - mikor, mekkora, hiba)
  - adatbazis-proba: a PEPPER_OLVAS felhasznaloval a kartyanaplo
    generatoranak erteke (GEN_ID(..., 0) - tablat nem olvas, nem ir)
  - az utolso frissitesi kiserlet eredmenye

Amit NEM kuld: nevet, kartyakodot, egyenleget, nyugtat - semmilyen
uzleti vagy szemelyes adatot.

Ha a valasz szerint ki van jelolve egy ujabb, alairt kiadas, atadja a
frissito.py-nak (ami az alairast es a verziot ellenorzi). Parancsot a
felho nem kuld; a gep csak jelent es frissul.

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
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

from common import (AGENT_VERSION, HERE, dpapi_protect, is_windows,
                    load_config, log, parse_list, run_isql, set_log)

LOG = os.path.join(HERE, "jelentes_log.txt")
MENTES = os.path.join(HERE, "mentes_allapot.json")
FRISSITES = os.path.join(HERE, "frissites_allapot.json")
UTOLSO = os.path.join(HERE, "jelentes_allapot.json")


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
    return {
        "helyszin": cfg.helyszin,
        "gep": socket.gethostname(),
        "agent_verzio": AGENT_VERSION,
        "python": platform.python_version(),
        "os": platform.platform()[:80],
        "ido": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": db_proba(cfg),
        "mentes": read_json(MENTES) or {},
        "frissites": read_json(FRISSITES),
    }


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


def cmd_titkosit():
    import getpass
    if not is_windows():
        sys.exit("A DPAPI csak Windows-on erheto el.")
    t = getpass.getpass("Token (nem jelenik meg): ").strip()
    if len(t) != 64:
        sys.exit("A token 64 karakteres hex szoveg - ellenorizd.")
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

    data = payload(cfg)
    if args.proba:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    try:
        resp = post(url, token, data)
    except Exception as e:
        resp = {"ok": False, "hiba": "kapcsolodasi hiba: {0}".format(e)}
    if args.proba:
        print("\nValasz:", json.dumps(resp, ensure_ascii=False))

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

    sys.exit(0 if resp.get("ok") else 1)


if __name__ == "__main__":
    main()
