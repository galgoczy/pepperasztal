# -*- coding: utf-8 -*-
"""
A tarhelyrol letoltott webmappa osszevetese a repoval (admin/public).

    python3 tarhely_ellenorzes.py <letoltott mappa> <repo admin/public> <agent mappa>

Kiirja:
  - VARATLAN: a szerveren van, a repoban nincs (a gepek kiadasai, a
    build.txt es az FTP-feltolto allapotfajlja kivetelevel);
  - ELTER: a repoban is megvan, de mas a tartalma;
  - HIANYZIK: a repoban van, a szerveren nincs;
  - a gyanus (varatlan / elteres) fajlokban talalt webshell-mintakat (csak a
    minta nevet, tartalmat nem);
  - az ugynok-kiadasok alairasanak ellenorzeset (a gepek kulcsaval);
  - a legutobb modositott fajlokat es a PHP hibanaplokat (csak meret,
    sorszam, utolso datum).
Kilepesi kod: 1, ha van varatlan vagy eltero fajl, vagy rossz alairas.
"""

import base64
import hashlib
import json
import os
import re
import sys
import time

KIHAGY = re.compile(r"(^|/)(config\.php|config\..+\.php|pepperadmin-config\.php)$|\.md$")
VART_EXTRA = re.compile(r"^(build\.txt|\.ftp-deploy-sync-state\.json|kiadasok/agent-[0-9][0-9.-]*\.(zip|json))$")
HIBANAPLO = re.compile(r"(^|/)(error_log|php_errorlog|.*\.log)$")
MINTAK = [
    ("eval(", re.compile(rb"\beval\s*\(", re.I)),
    ("assert(", re.compile(rb"\bassert\s*\(\s*\$", re.I)),
    ("base64_decode", re.compile(rb"base64_decode\s*\(", re.I)),
    ("gzinflate/gzuncompress", re.compile(rb"gz(inflate|uncompress|decode)\s*\(", re.I)),
    ("str_rot13", re.compile(rb"str_rot13\s*\(", re.I)),
    ("shell/exec", re.compile(rb"\b(shell_exec|passthru|system|exec|proc_open|popen|pcntl_exec)\s*\(", re.I)),
    ("create_function", re.compile(rb"create_function\s*\(", re.I)),
    ("preg_replace /e", re.compile(rb"preg_replace\s*\(\s*['\"].*/[a-z]*e[a-z]*['\"]", re.I)),
    ("valtozo-fuggvenyhivas $_GET/POST", re.compile(rb"\$_(GET|POST|REQUEST|COOKIE|SERVER)\s*\[[^\]]*\]\s*\(", re.I)),
    ("fajliras", re.compile(rb"(file_put_contents|fwrite|move_uploaded_file)\s*\(", re.I)),
    ("tavoli letoltes", re.compile(rb"(curl_exec|file_get_contents\s*\(\s*['\"]https?://)", re.I)),
    ("hosszu kodolt sor", re.compile(rb"[A-Za-z0-9+/=]{400,}")),
]


def fajlok(gyoker):
    ki = {}
    for d, _, fs in os.walk(gyoker):
        for f in fs:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, gyoker).replace(os.sep, "/")
            ki[rel] = p
    return ki


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def mintak(p):
    try:
        b = open(p, "rb").read()
    except Exception:
        return ["nem olvashato"]
    return [n for n, r in MINTAK if r.search(b)]


def main():
    tavoli, repo, agent = sys.argv[1:4]
    t = fajlok(tavoli)
    r = {k: v for k, v in fajlok(repo).items() if not KIHAGY.search(k)}
    rossz = 0

    print("== Osszesites")
    print("szerveren: %d fajl, repoban (feltoltendo): %d fajl" % (len(t), len(r)))

    varatlan = sorted(k for k in t if k not in r and not VART_EXTRA.match(k) and not HIBANAPLO.search(k))
    elter = sorted(k for k in t if k in r and sha(t[k]) != sha(r[k]))
    hianyzik = sorted(k for k in r if k not in t)

    print("\n== VARATLAN fajlok (a szerveren van, a repoban nincs): %d" % len(varatlan))
    for k in varatlan:
        st = os.stat(t[k])
        print("  %-50s %8d bajt  mod.: %s  minta: %s" % (
            k, st.st_size, time.strftime("%Y-%m-%d %H:%M", time.gmtime(st.st_mtime)),
            ", ".join(mintak(t[k])) or "-"))
    print("\n== ELTERO tartalom (a repoban mas): %d" % len(elter))
    for k in elter:
        st = os.stat(t[k])
        print("  %-50s mod.: %s  szerver sha256: %s  minta: %s" % (
            k, time.strftime("%Y-%m-%d %H:%M", time.gmtime(st.st_mtime)), sha(t[k])[:16],
            ", ".join(mintak(t[k])) or "-"))
    print("\n== HIANYZIK a szerverrol: %d" % len(hianyzik))
    for k in hianyzik:
        print("  " + k)
    rossz += len(varatlan) + len(elter)

    print("\n== build.txt a szerveren: %s" % (
        open(t["build.txt"]).read().strip() if "build.txt" in t else "nincs"))

    print("\n== Ugynok-kiadasok alairasa (a gepek kulcsaval)")
    sys.path.insert(0, agent)
    import frissito
    kulcs = frissito.load_key()
    zipok = sorted(k for k in t if re.match(r"^kiadasok/agent-.*\.zip$", k))
    if not zipok:
        print("  nincs kiadas")
    for k in zipok:
        js = k[:-4] + ".json"
        try:
            data = open(t[k], "rb").read()
            m = json.load(open(t[js]))
            ok = (hashlib.sha256(data).hexdigest() == m["sha256"] and kulcs and
                  frissito.rsa_verify_sha256(data, base64.b64decode(m["sig"]), *kulcs))
        except Exception as e:
            ok, m = False, {"hiba": str(e)[:80]}
        print("  %-40s %s  verzio %s, commit %s" % (
            k, "ALAIRAS RENDBEN" if ok else "ROSSZ ALAIRAS!", m.get("verzio"), m.get("commit")))
        if not ok:
            rossz += 1

    print("\n== A 25 legutobb modositott fajl a szerveren (UTC)")
    for k in sorted(t, key=lambda k: -os.stat(t[k]).st_mtime)[:25]:
        print("  %s  %s" % (time.strftime("%Y-%m-%d %H:%M", time.gmtime(os.stat(t[k]).st_mtime)), k))

    naplok = sorted(k for k in t if HIBANAPLO.search(k))
    print("\n== PHP hibanaplok: %d" % len(naplok))
    for k in naplok:
        sorok = open(t[k], "rb").read().decode("utf-8", "replace").splitlines()
        datumok = [m.group(1) for m in (re.match(r"^\[([^\]]+)\]", s) for s in sorok) if m]
        gyanus = sum(1 for s in sorok if re.search(r"eval\(|base64|shell|passthru|\.\./|/etc/passwd", s, re.I))
        print("  %-40s %6d sor, utolso: %s, gyanus kulcsszavas sor: %d" % (
            k, len(sorok), datumok[-1] if datumok else "-", gyanus))

    print("\n== EREDMENY: %s" % ("GYANUS ELTERES - nezd at a fenti listat" if rossz else
                                 "a szerver fajljai megegyeznek a repoval"))
    sys.exit(1 if rossz else 0)


if __name__ == "__main__":
    main()
