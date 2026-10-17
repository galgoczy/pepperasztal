# -*- coding: utf-8 -*-
"""
kartyak.py - a feltoltos (1-es tipusu) kartyak mozgasai es egyenlegei a
Pepper Adminnak. A jelentes.py hivja percenkent; CSAK OLVAS (PEPPER_OLVAS).

Mit kuld:
  - naplo: a KARTYANAPLO uj sorai feltoltos kartyakra - naplo-ID,
    kartya-ID, tipus (FK = koltes, KF = feltoltes, ...), osszeg, elotte
    levo egyenleg, idopont. Lapozva (alap 300 sor/jelentes), igy az
    elozmeny is fokozatosan felmegy.
  - pillanatkep: minden feltoltos kartya egyenlege (AKT_KP), ha volt uj
    naplosor, vagy 15 perc eltelt (a kasszaban kezzel atirt egyenleg is
    latsszon).
  - egyeztetes: naponta egyszer (02:00 utan) minden feltoltos kartyara
    AKT_KP = utolso naplosor AKT + OSSZEG. Az eltero kartyak listaja.

Amit NEM kuld: nevet, kartyakodot, tulajdonost, szemelyzeti kartyat.

Kurzor: a gep csak akkor lep tovabb, ha a szerver visszaigazolta, hogy
megkapta (naplo_ig). Minden lekeresnel az utolso 20 ID-t ujra kuldi: a
generator-ertek a COMMIT elott kiosztodik, igy egy kisebb ID-ju sor
kesobb is megjelenhet. A szerver a naplo-ID alapjan duplikaciot szur.
"""

import json
import os
import time

from common import HERE, parse_list, run_isql

ALLAPOT = os.path.join(HERE, "kartya_allapot.json")
VISSZA = 20                 # ennyi ID-t mindig ujraolvasunk
PILLANAT_PERC = 15
UJRANEZ_PERC = 10           # uj sor nelkul is ujraolvassa az ablakot ennyi percenkent
EGYEZTETES_ORA = 2


def _allapot():
    try:
        with open(ALLAPOT, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ment(d):
    tmp = ALLAPOT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, ALLAPOT)


def _num(v):
    """'-960.00' -> '-960.00' (ellenorzott, ket tizedes szoveg)."""
    if v is None:
        return None
    return "{0:.2f}".format(float(v))


def _ido(v):
    return (v or "")[:19]


def _rows(cfg, sql, cols):
    out, err = run_isql(cfg, "SET LIST ON;\n" + sql, user_key="olvas")
    if err and not out.strip():
        raise RuntimeError(err.strip().splitlines()[0][:160])
    return parse_list(out, cols)


def naplo_sorok(cfg, tol, ig):
    """KARTYANAPLO (tol, ig] feltoltos kartyakra, ID szerint."""
    rows = _rows(cfg, (
        "SELECT L.ID AS ID, L.KARTYA AS K, L.TTIPUS AS T, L.OSSZEG AS O, "
        "L.AKT AS A, L.DATUM AS D FROM KARTYANAPLO L JOIN KARTYATORZS KT "
        "ON KT.ID = L.KARTYA WHERE L.ID > {0} AND L.ID <= {1} AND "
        "KT.TIPUS = 1 ORDER BY L.ID;").format(int(tol), int(ig)),
        ["ID", "K", "T", "O", "A", "D"])
    return [{"id": int(r["ID"]), "kartya": int(r["K"]),
             "tipus": (r.get("T") or "").strip()[:4],
             "osszeg": _num(r.get("O")), "elotte": _num(r.get("A")),
             "ido": _ido(r.get("D"))} for r in rows if r.get("ID")]


def egyenlegek(cfg):
    rows = _rows(cfg, "SELECT K.ID AS ID, K.AKT_KP AS E, K.ERVENYES AS V "
                      "FROM KARTYATORZS K WHERE K.TIPUS = 1;", ["ID", "E", "V"])
    return [{"id": int(r["ID"]), "egyenleg": _num(r.get("E")),
             "ervenyes": 1 if (r.get("V") or "").strip() == "1" else 0}
            for r in rows if r.get("ID")]


def egyeztetes(cfg):
    """AKT_KP = utolso naplosor AKT + OSSZEG, minden feltoltos kartyara."""
    kartyak = dict((k["id"], k) for k in egyenlegek(cfg))
    rows = _rows(cfg, (
        "SELECT L.ID AS ID, L.KARTYA AS K, L.OSSZEG AS O, L.AKT AS A FROM "
        "KARTYANAPLO L JOIN KARTYATORZS KT ON KT.ID = L.KARTYA WHERE "
        "KT.TIPUS = 1;"), ["ID", "K", "O", "A"])
    utolso = {}
    for r in rows:
        k, i = int(r["K"]), int(r["ID"])
        if k not in utolso or i > utolso[k][0]:
            utolso[k] = (i, float(r.get("A") or 0) + float(r.get("O") or 0))
    elteres, nincs = [], 0
    for kid, k in sorted(kartyak.items()):
        if kid not in utolso:
            nincs += 1
            continue
        szerint = round(utolso[kid][1], 2)
        if abs(float(k["egyenleg"] or 0) - szerint) > 0.005:
            elteres.append({"kartya": kid, "egyenleg": k["egyenleg"],
                            "naplo_szerint": "{0:.2f}".format(szerint)})
    return {"ido": time.strftime("%Y-%m-%d %H:%M:%S"), "kartyak": len(kartyak),
            "naplo_nelkul": nincs, "elteres": elteres[:200]}


def gyujt(cfg, naplo_gen):
    """A jelentesbe kerulo resz. naplo_gen: GEN_ID(GEN_KARTYANAPLO, 0)."""
    if not cfg.kartyak["kuldes"]:
        return None
    st = _allapot()
    most = time.time()
    kurzor = st.get("kurzor")
    if kurzor is None:
        kurzor = max(0, int(cfg.kartyak["kezdet"]))
    ki = {"kurzor": kurzor, "gen": naplo_gen}
    if naplo_gen is None:
        return ki

    if naplo_gen < kurzor - VISSZA:
        # A generator visszalepett (pl. visszaallitott adatbazis): elolrol
        # az aktualis ertektol; a szerver a duplikaciot kiszuri.
        kurzor = ki["kurzor"] = max(0, naplo_gen - VISSZA)
        st["kurzor"] = kurzor
        _ment(st)

    uj = naplo_gen > kurzor
    if uj or most - st.get("ujranez", 0) > UJRANEZ_PERC * 60:
        tol = max(0, kurzor - VISSZA)
        ig = min(naplo_gen, kurzor + cfg.kartyak["lap"])
        ki["naplo"] = {"tol": tol, "ig": ig, "sorok": naplo_sorok(cfg, tol, ig)}

    if (st.get("pillanat_gen") != naplo_gen
            or most - st.get("pillanat_ido", 0) > PILLANAT_PERC * 60):
        ki["pillanatkep"] = {"ido": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "gen": naplo_gen, "lista": egyenlegek(cfg)}

    nap = time.strftime("%Y-%m-%d")
    if (st.get("egyeztetes_nap") != nap
            and int(time.strftime("%H")) >= EGYEZTETES_ORA):
        ki["egyeztetes"] = egyeztetes(cfg)
    return ki


def nyugtaz(ki, resp):
    """A szerver valasza utan: a kurzor csak a visszaigazolt ig-ig lep."""
    if not ki or not resp.get("ok"):
        return
    st = _allapot()
    st.setdefault("kurzor", ki["kurzor"])
    n = ki.get("naplo")
    if n is not None and resp.get("naplo_ig") == n["ig"]:
        st["kurzor"] = max(st["kurzor"], n["ig"])
        st["ujranez"] = time.time()
    p = ki.get("pillanatkep")
    if p is not None and resp.get("pillanatkep_ok"):
        st["pillanat_gen"] = p["gen"]
        st["pillanat_ido"] = time.time()
    if ki.get("egyeztetes") is not None and resp.get("egyeztetes_ok"):
        st["egyeztetes_nap"] = ki["egyeztetes"]["ido"][:10]
    _ment(st)
