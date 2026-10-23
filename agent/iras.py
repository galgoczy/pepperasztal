# -*- coding: utf-8 -*-
"""
iras.py - egyenleg-modositas a Pepper Admin utasitasara (PEPPER_VIP).

Csak akkor ir, ha az ini-ben [iras] be = igen. Kulonben minden utasitasra
"nincs bekapcsolva" valaszt ad, es semmihez nem nyul.

Mit tud: feltoltes (+) es levonas (-) egy feltoltos (1-es tipusu) kartyan,
pontosan ugy, ahogy a NovoHost sajat feltoltese (KF naplosor; a levonast
a NovoHost is negativ KF-fel rogziti):
  1. a naplosor ID-ja a GEN_KARTYANAPLO generatorbol, ELORE (a generator
     leptetese nem tranzakcios: visszagorgetes utan sem kapja meg mas);
  2. egy tranzakcioban, majd COMMIT:
       UPDATE ... SET LIMIT_KP = AKT_KP + x          (a regi AKT_KP-bol)
       UPDATE ... SET AKT_KP = AKT_KP + x, AKT_FORG = 0
       INSERT INTO KARTYANAPLO ... SELECT ..., AKT_KP - x (= elotte) ...
     KET kulon UPDATE: az InterBase egy utasitason belul mar a frissitett
     AKT_KP-val szamolna (eles tapasztalat: 30 lett 20 helyett).
  3. visszaolvasas UJ kapcsolatbol: megvan-e a naplosor, mennyi az egyenleg.
     Az isql hiba utan is tovabbmegy, ezert a sikert soha nem a stderr-bol,
     hanem a visszaolvasasbol iteljuk meg.

Minden utasitas pontosan egyszer fut le: az azonositojat es a lefoglalt
naplo-ID-t meg az iras ELOTT elmentjuk (iras_allapot.json). Ha a gep
kozben leall, a kovetkezo futas a naplo-ID alapjan eldonti, lefutott-e -
ujra nem probalja.
"""

import json
import os
import re
import time

from common import HERE, log, parse_list, run_isql

ALLAPOT = os.path.join(HERE, "iras_allapot.json")
MAX_OSSZEG = 1000000.0


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


def _sor(cfg, sql, cols):
    out, err = run_isql(cfg, "SET LIST ON;\n" + sql, user_key="vip")
    rows = parse_list(out, cols)
    return rows, err


def kartya(cfg, kid):
    rows, err = _sor(cfg, "SELECT K.TIPUS AS T, K.AKT_KP AS E, K.LIMIT_KP AS L, "
                          "K.ERVENYES AS V FROM KARTYATORZS K WHERE K.ID = {0};"
                     .format(int(kid)), ["T", "E", "L", "V"])
    return (rows[0] if rows else None), err


def naplosor(cfg, nid):
    rows, _ = _sor(cfg, "SELECT L.ID AS ID, L.KARTYA AS K, L.OSSZEG AS O, "
                        "L.AKT AS A FROM KARTYANAPLO L WHERE L.ID = {0};"
                   .format(int(nid)), ["ID", "K", "O", "A"])
    return rows[0] if rows else None


def _eredmeny(cfg, p, nid):
    """A tenyleges allapot visszaolvasva (uj kapcsolat)."""
    sor = naplosor(cfg, nid)
    k, _ = kartya(cfg, p["kartya"])
    egyenleg = k.get("E") if k else None
    if sor and int(sor["K"]) == p["kartya"] and abs(float(sor["O"]) - p["osszeg"]) < 0.005:
        return {"id": p["id"], "ok": True, "naplo_id": nid,
                "elotte": "{0:.2f}".format(float(sor["A"])), "egyenleg": egyenleg}
    return {"id": p["id"], "ok": False, "naplo_id": nid, "egyenleg": egyenleg,
            "hiba": "a naplosor nem jott letre - az egyenleget kezzel ellenorizni kell"
            if sor is None else "a naplosor nem egyezik"}


def _ellenoriz(p):
    try:
        pid = int(p.get("id"))
        kid = int(p.get("kartya"))
        x = round(float(p.get("osszeg")), 2)
    except (TypeError, ValueError):
        return None, "hibas utasitas"
    if p.get("tipus") != "egyenleg":
        return None, "ismeretlen utasitas: {0}".format(str(p.get("tipus"))[:20])
    if pid <= 0 or kid <= 0 or x == 0 or abs(x) > MAX_OSSZEG:
        return None, "ervenytelen kartya vagy osszeg"
    return {"id": pid, "kartya": kid, "osszeg": x}, None


def vegrehajt(cfg, parancsok):
    """Az admin utasitasai -> eredmenyek (a kovetkezo jelentesben mennek fel)."""
    if not parancsok:
        return []
    st = _allapot()
    kesz = st.setdefault("kesz", {})
    folyamatban = st.setdefault("folyamatban", {})
    ki = []
    for nyers in parancsok[:20]:
        sid = str(nyers.get("id"))
        if sid in kesz:                       # mar lefutott: csak ujrajelentjuk
            ki.append(kesz[sid])
            continue
        if not cfg.iras["be"]:
            ki.append({"id": nyers.get("id"), "ok": False,
                       "hiba": "ezen a gepen az iras nincs bekapcsolva ([iras] be = igen)"})
            continue
        if not cfg.users["vip"][1]:
            ki.append({"id": nyers.get("id"), "ok": False,
                       "hiba": "nincs PEPPER_VIP jelszo az ini [vip] szakaszaban"})
            continue
        try:
            e = _egy(cfg, nyers, st, kesz, folyamatban)
        except Exception as ex:
            # Barmi varatlan: lathato hiba az adminban. Ha mar lefoglaltuk a
            # naplo-ID-t, a kovetkezo futas a naplobol donti el, mi tortent.
            e = {"id": nyers.get("id"), "ok": False, "hiba": "ugynok-hiba: " + str(ex)[:200]}
            if sid not in folyamatban:
                kesz[sid] = e
        _ment(st)
        ki.append(e)
    # A szerver visszaigazolasaig minden jelentes viszi az eredmenyeket.
    kuld = st.setdefault("kuldendo", {})
    for e in ki:
        kuld[str(e.get("id"))] = e
    _ment(st)
    return ki


def _egy(cfg, nyers, st, kesz, folyamatban):
    """Egy utasitas vegrehajtasa. Visszaadja az eredmenyt."""
    sid = str(nyers.get("id"))
    p, hiba = _ellenoriz(nyers)
    if hiba:
        kesz[sid] = {"id": nyers.get("id"), "ok": False, "hiba": hiba}
        return kesz[sid]
    if sid in folyamatban:
        # Az elozo futas az iras kozben allt le: lefutott-e?
        e = _eredmeny(cfg, p, folyamatban[sid])
        if not e["ok"]:
            e["hiba"] = "megszakadt futas, nem ismeteljuk: " + e.get("hiba", "")
        kesz[sid] = e
        del folyamatban[sid]
        _ment(st)
        return e

    k, err = kartya(cfg, p["kartya"])
    if not k:
        e = {"id": p["id"], "ok": False, "hiba": "nincs ilyen kartya" + (
            ": " + err.strip().splitlines()[0][:120] if err else "")}
    elif (k.get("T") or "").strip() != "1":
        e = {"id": p["id"], "ok": False, "hiba": "csak feltoltos (1-es tipusu) kartya"}
    elif float(k.get("E") or 0) + p["osszeg"] < -0.005:
        e = {"id": p["id"], "ok": False,
             "hiba": "az egyenleg nem mehet minuszba (most {0})".format(k.get("E"))}
    else:
        e = None
    if e:
        kesz[sid] = e
        _ment(st)
        return e

    g, err = _sor(cfg, "SELECT GEN_ID(GEN_KARTYANAPLO, 1) AS G FROM RDB$DATABASE;", ["G"])
    if not g or not g[0].get("G"):
        return {"id": p["id"], "ok": False, "hiba": "naplo-ID nem kerheto: " +
                (err or "").strip()[:120]}
    nid = int(g[0]["G"])
    folyamatban[sid] = nid
    _ment(st)                              # az iras ELOTT

    x = "{0:.2f}".format(p["osszeg"])
    most = time.strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "UPDATE KARTYATORZS SET LIMIT_KP = AKT_KP + ({x}) WHERE ID = {kid};\n"
        "UPDATE KARTYATORZS SET AKT_KP = AKT_KP + ({x}), AKT_FORG = 0 "
        "WHERE ID = {kid};\n"
        "INSERT INTO KARTYANAPLO (ID, PG, KARTYA, KEZELO, TTIPUS, OSSZEG, AKT, "
        "DATUM) SELECT {nid}, {pg}, K.ID, {kez}, 'KF', {x}, K.AKT_KP - ({x}), "
        "'{most}' FROM KARTYATORZS K WHERE K.ID = {kid};"
    ).format(x=x, kid=p["kartya"], nid=nid, pg=int(cfg.iras["pg"]),
             kez=int(cfg.iras["kezelo"]), most=most)
    out, err = run_isql(cfg, sql, user_key="vip", commit=True)
    e = _eredmeny(cfg, p, nid)
    if err and not e["ok"]:
        e["hiba"] = e.get("hiba", "") + " | isql: " + err.strip().splitlines()[0][:160]
    log("iras: utasitas {0}, kartya {1}, {2} Ft -> {3}".format(
        p["id"], p["kartya"], x, "OK" if e["ok"] else "HIBA " + e.get("hiba", "")))
    kesz[sid] = e
    del folyamatban[sid]
    # csak az utolso 500 eredmenyt tartjuk meg
    if len(kesz) > 500:
        for regi in sorted(kesz, key=lambda s: int(s) if re.match(r"^\d+$", s) else 0)[:-500]:
            del kesz[regi]
    _ment(st)
    return e


def kuldendo():
    """A meg vissza nem igazolt eredmenyek (minden jelentes viszi)."""
    return list(_allapot().get("kuldendo", {}).values())


def nyugtaz(resp):
    ack = set(str(i) for i in (resp.get("parancs_ack") or []))
    if not ack:
        return
    st = _allapot()
    kuld = st.get("kuldendo", {})
    for i in ack:
        kuld.pop(i, None)
    st["kuldendo"] = kuld
    _ment(st)
