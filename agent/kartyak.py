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

A feltoltos kartyak neve a pillanatkeppel megy fel (a szerver titkositva
tarolja, az adminban alapbol csillagozva latszik). Kikapcsolhato:
[kartyak] nevek = nem - ekkor a szerver a mar tarolt neveket is torli.
Ugyanigy a kartyakod (KARTYA, a vonalkodhoz): [kartyak] kodok = nem.

  - vasarlasok: a friss (3 napon beluli) koltesekhez a nyugta tetelei
    (termeknev, mennyiseg, ertek, kategoria). Parositas: kartya + osszeg +
    a nyugta lezarasa +-15 percen belul. Csak feltoltos kartyas fizetes.

Amit NEM kuld: tulajdonos-adatot, szemelyzeti kartyat.

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


def egyenlegek(cfg, nevek=False, kodok=False):
    rows = _rows(cfg, "SELECT K.ID AS ID, K.AKT_KP AS E, K.ERVENYES AS V, "
                      "K.NEV AS N" + (", K.KARTYA AS C" if kodok else "") +
                      " FROM KARTYATORZS K WHERE K.TIPUS = 1;",
                 ["ID", "E", "V", "N", "C"])
    ki = []
    for r in rows:
        if not r.get("ID"):
            continue
        d = {"id": int(r["ID"]), "egyenleg": _num(r.get("E")),
             "ervenyes": 1 if (r.get("V") or "").strip() == "1" else 0}
        if nevek:
            d["nev"] = " ".join((r.get("N") or "").split())[:40]
        if kodok:
            kod = (r.get("C") or "").strip()
            if kod and len(kod) <= 20:
                d["kod"] = kod
        ki.append(d)
    return ki


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


VASARLAS_NAP = 3            # ennel regebbi koltesnel nem keresunk nyugtat
VASARLAS_ABLAK = 3000       # az utolso ennyi nyugtaban keresunk
VASARLAS_PROBA = 5          # ennyiszer probaljuk parositani, utana feladjuk
VASARLAS_PERC = 15          # nyugta lezarasa es naplosor kozti max. elteres


def _epoch(s):
    try:
        return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def _in_lista(szamok):
    return ", ".join(str(int(x)) for x in sorted(set(szamok)))


def vasarlasok(cfg, koltesek, foglalt):
    """
    Koltes (FK naplosor) -> a nyugta tetelei. Parositas: ugyanaz a kartya,
    a VIP-fizetes osszege = a koltes, a nyugta lezarasa +-15 percen belul;
    tobb jelolt kozul az idoben legkozelebbi, meg fel nem hasznalt.
    Visszaad: (talalatok, parositatlan naplo-ID-k).
    """
    if not koltesek:
        return [], []
    mx = _rows(cfg, "SELECT MAX(F.ID) AS M FROM NYUGTAFEJ F;", ["M"])
    if not mx or not mx[0].get("M"):
        return [], [k["id"] for k in koltesek]
    lo = max(0, int(mx[0]["M"]) - VASARLAS_ABLAK)
    fiz = _rows(cfg, (
        "SELECT N.FEJ AS FEJ, N.KKODID AS K, N.FORINT AS F, N.LEZARVA AS L "
        "FROM NYUGTAFIZETES N JOIN KARTYATORZS KT ON KT.ID = N.KKODID WHERE "
        "N.FEJ > {0} AND N.FIZTIPID = 10 AND N.FIZTIP = 'FIZ' AND "
        "KT.TIPUS = 1;").format(lo), ["FEJ", "K", "F", "L"])
    jeloltek = {}
    for r in fiz:
        if not r.get("FEJ") or not r.get("K"):
            continue
        jeloltek.setdefault(int(r["K"]), []).append(
            (int(r["FEJ"]), float(r.get("F") or 0), _epoch(r.get("L"))))

    par, nincs = {}, []
    hasznalt = set(foglalt)
    for k in sorted(koltesek, key=lambda x: x["id"]):
        osszeg = -float(k["osszeg"] or 0)
        t = _epoch(k["ido"])
        legjobb = None
        for fej, forint, lz in jeloltek.get(k["kartya"], []):
            if fej in hasznalt or abs(forint - osszeg) > 0.005:
                continue
            d = abs(lz - t) if (lz is not None and t is not None) else 0
            if d <= VASARLAS_PERC * 60 and (legjobb is None or d < legjobb[1]):
                legjobb = (fej, d)
        if legjobb:
            par[k["id"]] = legjobb[0]
            hasznalt.add(legjobb[0])
        else:
            nincs.append(k["id"])
    if not par:
        return [], nincs

    fejek = _in_lista(par.values())
    tetelek = _rows(cfg, (
        "SELECT T.FEJ AS FEJ, T.NEV AS N, T.MENNYISEG AS M, T.VEGERTEK AS V, "
        "T.EAZO AS E FROM NYUGTATETEL T WHERE T.FEJ IN ({0});").format(fejek),
        ["FEJ", "N", "M", "V", "E"])
    vegertek = dict((int(r["ID"]), _num(r.get("V"))) for r in _rows(cfg, (
        "SELECT F.ID AS ID, F.VEGERTEK AS V FROM NYUGTAFEJ F WHERE F.ID IN "
        "({0});").format(fejek), ["ID", "V"]) if r.get("ID"))
    eazok = [int(r["E"]) for r in tetelek if (r.get("E") or "").strip().lstrip("-").isdigit()]
    kat = {}
    if eazok:
        tip = dict((int(r["ID"]), int(r["T"])) for r in _rows(cfg, (
            "SELECT E.ID AS ID, E.TIPUS AS T FROM ETELFAJ E WHERE E.ID IN "
            "({0});").format(_in_lista(eazok)), ["ID", "T"])
            if r.get("ID") and r.get("T"))
        nevek = dict((int(r["ID"]), (r.get("N") or "").strip()) for r in _rows(
            cfg, "SELECT T.ID AS ID, T.NEV AS N FROM ETELTIP T;", ["ID", "N"])
            if r.get("ID"))
        for e, t in tip.items():
            kat[e] = (t, nevek.get(t, ""))

    per_fej = {}
    for r in tetelek:
        e = int(r["E"]) if (r.get("E") or "").strip().lstrip("-").isdigit() else None
        kt = kat.get(e, (None, ""))
        per_fej.setdefault(int(r["FEJ"]), []).append({
            "nev": " ".join((r.get("N") or "").split())[:60],
            "menny": round(float(r.get("M") or 0), 3),
            "ertek": _num(r.get("V")), "kat_id": kt[0], "kat": kt[1][:40]})
    ki = []
    kmap = dict((k["id"], k) for k in koltesek)
    for nid, fej in sorted(par.items()):
        k = kmap[nid]
        ki.append({"naplo_id": nid, "nyugta": fej, "kartya": k["kartya"],
                   "ido": k["ido"], "osszeg": _num(-float(k["osszeg"] or 0)),
                   "vegertek": vegertek.get(fej), "tetelek": per_fej.get(fej, [])[:100]})
    return ki, nincs


def _vasarlas_jeloltek(st, sorok):
    """Uj, friss koltesek + a korabban parositatlanok (proba-szamlaloval)."""
    kesz = set(st.get("vas_kesz", []))
    var = st.get("vas_var", {})
    hatar = time.time() - VASARLAS_NAP * 86400
    for r in sorok:
        if (r["tipus"] == "FK" and r["id"] not in kesz and str(r["id"]) not in var
                and (_epoch(r["ido"]) or 0) >= hatar):
            var[str(r["id"])] = {"kartya": r["kartya"], "osszeg": r["osszeg"],
                                 "ido": r["ido"], "proba": 0}
    st["vas_var"] = var
    return [dict(v, id=int(k)) for k, v in var.items()]


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

    # Mit vett? A friss koltesekhez a nyugta tetelei (a parositatlanokat a
    # kovetkezo futasok ujraprobaljak, VASARLAS_PROBA-szor).
    jeloltek = _vasarlas_jeloltek(st, ki.get("naplo", {}).get("sorok", []))
    if jeloltek:
        talalt, nincs = vasarlasok(cfg, jeloltek, st.get("vas_nyugtak", []))
        if talalt:
            ki["vasarlasok"] = talalt
        for nid in nincs:
            v = st["vas_var"].get(str(nid))
            if v is not None:
                v["proba"] = v.get("proba", 0) + 1
                if v["proba"] >= VASARLAS_PROBA:
                    del st["vas_var"][str(nid)]
        _ment(st)

    kodok = bool(cfg.kartyak["kodok"])
    if (st.get("pillanat_gen") != naplo_gen
            or st.get("pillanat_kodok") != kodok
            or most - st.get("pillanat_ido", 0) > PILLANAT_PERC * 60):
        nevek = bool(cfg.kartyak["nevek"])
        ki["pillanatkep"] = {"ido": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "gen": naplo_gen, "nevek": nevek, "kodok": kodok,
                             "lista": egyenlegek(cfg, nevek, kodok)}

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
        st["pillanat_kodok"] = p.get("kodok", False)
    if ki.get("egyeztetes") is not None and resp.get("egyeztetes_ok"):
        st["egyeztetes_nap"] = ki["egyeztetes"]["ido"][:10]
    ok = set(resp.get("vasarlas_ok") or [])
    if ok:
        kesz = st.get("vas_kesz", [])
        nyugtak = st.get("vas_nyugtak", [])
        for v in ki.get("vasarlasok", []):
            if v["naplo_id"] in ok:
                kesz.append(v["naplo_id"])
                nyugtak.append(v["nyugta"])
                st.get("vas_var", {}).pop(str(v["naplo_id"]), None)
        st["vas_kesz"] = kesz[-2000:]
        st["vas_nyugtak"] = nyugtak[-2000:]
    _ment(st)
