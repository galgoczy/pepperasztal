# -*- coding: utf-8 -*-
"""
setup_users.py - korlatozott InterBase felhasznalok a SYSDBA helyett.

KET FELHASZNALO
  PEPPER_OLVAS  csak SELECT, minden tablara, kiveve a szemelyes adatot
                tartalmazokat (alapbol: KARTYATULAJDONOS). Ezzel fut a
                felderites, a menu/nyugta olvasas, a koltes-figyeles.
  PEPPER_VIP    a VIP-ugynok. SELECT + INSERT a kartya- es naplotablara,
                UPDATE CSAK az egyenleg-oszlopokra. DELETE sehol, a
                nyugta- es etel-tablakhoz semmi joga.

Mit ved: NEM a helyi tamado ellen (aki rendszergazda a POS gepen, mindent
elér), hanem a sajat hibaink es egy feltort felho ellen - felso korlatot
ad a karnak. A legrosszabb eset igy "valaki egyenleget irt", nem
"elveszett egy honap forgalma".

A SYSDBA jelszavahoz NEM nyulunk - a NovoHost is azt hasznalja.

LEPESEK (a POS gepen, rendszergazdakent):
    python setup_users.py titkosit    a SYSDBA jelszo DPAPI-blobba (ini-be)
    python setup_users.py jelszo      uj jelszavak -> masold az ini-be
    python setup_users.py terv        mit csinalna (semmit nem valtoztat)
    python setup_users.py letrehoz    felhasznalok + jogok + ellenorzes
    python setup_users.py ellenoriz   csak az ellenorzes, barmikor
    python setup_users.py ellenoriz --triggerproba 610
                                      + valodi, visszagorgetett UPDATE a
                                        tesztkartyan (triggerek joga)
    python setup_users.py visszavon   minden jog vissza, felhasznalok torolve

Barmelyik lepes ujrafuttathato: a letrehoz meglevo felhasznalonak csak a
jelszavat allitja, a GRANT pedig ismetelve sem art.
"""

import argparse
import json
import os
import random
import re
import string
import sys
import time

from common import (AGENT_VERSION, HERE, ConfigError, dpapi_protect, is_windows,
                    load_config, log, parse_list, run_isql, run_tool,
                    set_log)

ALLAPOT = os.path.join(HERE, "setup_users_allapot.json")
IDENT = re.compile(r"^[A-Z0-9_$]+$")

# A szemelyes adatot tartalmazo tablak - az olvaso felhasznalo sem latja.
# Az ini [olvas] kihagy = ... sora feluliraja.
OLVAS_KIHAGY = ("KARTYATULAJDONOS",)

VIP_SELECT = ("KARTYATORZS", "KARTYANAPLO", "KARTYATIPUS")
VIP_INSERT = ("KARTYATORZS", "KARTYANAPLO")
VIP_UPDATE_COLS = ("AKT_KP", "LIMIT_KP", "AKT_FORG", "KARTYA")

# Amit a triggerek/eljarasok maguk csinalnak beszuraskor. Ezeket a
# jogokat a TRIGGER-nek adjuk, nem a felhasznalonak - igy a PEPPER_VIP
# maga nem tud a KARTYATULAJDONOS-ba irni, csak a NovoHost sajat
# triggere, a kartya beszurasakor.
#   (jog, objektum-tipus, objektum, kapo-tipus, kapo)
#
# Az eles felderites (Szentkiralyi, 2026-10-17) szerint:
#   - a BU0 (modositas elott) is meghivja az NH$CHK_DBL_VIP_CARD-ot,
#     tehat minden egyenleg-UPDATE-nel lefut;
#   - a CHECK_54 ellenorzo trigger UPDATE utan a KARTYATULAJDONOS-t olvassa.
OBJEKTUM_JOGOK = (
    ("INSERT", "", "KARTYATULAJDONOS", "TRIGGER", "KARTYATORZS_AI0"),
    ("EXECUTE", "PROCEDURE", "NH$CHK_DBL_VIP_CARD", "TRIGGER",
     "KARTYATORZS_BI0"),
    ("EXECUTE", "PROCEDURE", "NH$CHK_DBL_VIP_CARD", "TRIGGER",
     "KARTYATORZS_BU0"),
    ("SELECT", "", "KARTYATORZS", "PROCEDURE", "NH$CHK_DBL_VIP_CARD"),
    ("SELECT", "", "KARTYATULAJDONOS", "TRIGGER", "CHECK_54"),
)

# RDB$USER_PRIVILEGES.RDB$USER_TYPE: 2 = trigger, 5 = eljaras
KAPO_TIPUS = {"TRIGGER": "2", "PROCEDURE": "5"}
JOG_BETU = {"SELECT": "S", "INSERT": "I", "UPDATE": "U", "DELETE": "D",
            "EXECUTE": "X"}


# ===========================================================================
# jelszo
# ===========================================================================

def cmd_titkosit(cfg, args):
    """Egy meglevo jelszo (pl. a SYSDBA-e) DPAPI-blobba, az ini-be."""
    import getpass
    if not is_windows():
        sys.exit("A DPAPI csak Windows-on erheto el.")
    pw = getpass.getpass("Jelszo (nem jelenik meg): ")
    if not pw:
        sys.exit("Ures jelszo - kilepek.")
    print("\npassword_dpapi = {0}\n".format(dpapi_protect(pw)))
    print("Ezt a sort masold a megfelelo szakaszba (pl. [sysdba]), a "
          "nyilt 'password =' sort pedig torold.")


def cmd_jelszo(cfg, args):
    """
    Az InterBase (IB6, regi hitelesites) a jelszonak CSAK AZ ELSO 8
    KARAKTERET nezi. Ezert pontosan 8 veletlen karakter, betu+szam -
    idezojel, pontosvesszo nelkul, mert a jelszo az isql CONNECT
    soraba kerul.
    """
    rnd = random.SystemRandom()
    abc = string.ascii_letters + string.digits
    print("; Masold be a pepper_agent.ini-be (a meglevo sorok helyere).")
    print("; A jelszot nem kell megjegyezni: gepenkent kulon van, es ha")
    print("; elveszik, a 'jelszo' + 'letrehoz' ujra beallitja.\n")
    for key in ("olvas", "vip"):
        pw = "".join(rnd.choice(abc) for _ in range(8))
        print("[{0}]".format(key))
        print("user = {0}".format(cfg.user(key)))
        if is_windows():
            print("password_dpapi = {0}".format(dpapi_protect(pw)))
        else:
            print("password = {0}".format(pw))
        print("")
    if not is_windows():
        print("; FIGYELEM: nem Windows - DPAPI nelkul, nyilt jelszo.")


# ===========================================================================
# Objektumok es jogok felmerese
# ===========================================================================

def q(cfg, sql, cols, user="sysdba"):
    out, err = run_isql(cfg, "SET LIST ON;\n" + sql, user_key=user)
    return parse_list(out, cols), err


def user_tables(cfg):
    rows, err = q(cfg,
                  "SELECT RDB$RELATION_NAME AS T FROM RDB$RELATIONS WHERE "
                  "(RDB$SYSTEM_FLAG IS NULL OR RDB$SYSTEM_FLAG = 0);", ["T"])
    if err:
        raise RuntimeError("Tablalista: " + err)
    return sorted(r["T"].strip() for r in rows if r.get("T"))


def exists(cfg, kind, name):
    tab = {"TRIGGER": ("RDB$TRIGGERS", "RDB$TRIGGER_NAME"),
           "PROCEDURE": ("RDB$PROCEDURES", "RDB$PROCEDURE_NAME"),
           "": ("RDB$RELATIONS", "RDB$RELATION_NAME")}[kind]
    rows, _ = q(cfg, "SELECT COUNT(*) AS N FROM {0} WHERE {1} = '{2}';"
                .format(tab[0], tab[1], name), ["N"])
    return bool(rows) and rows[0].get("N") not in (None, "0")


def privileges(cfg):
    """{(kapo, kapo_tipus, jog, objektum, mezo)} a PEPPER_* es a trigger/
    eljaras-jogokra. Uj kapcsolatbol - ez a valosag, nem a szandek."""
    rows, err = q(cfg,
                  "SELECT RDB$USER AS U, RDB$USER_TYPE AS UT, RDB$PRIVILEGE "
                  "AS P, RDB$RELATION_NAME AS R, RDB$FIELD_NAME AS F FROM "
                  "RDB$USER_PRIVILEGES WHERE RDB$USER STARTING WITH 'PEPPER' "
                  "OR RDB$USER_TYPE IN (2, 5);", ["U", "UT", "P", "R", "F"])
    if err:
        raise RuntimeError("Jogok lekerdezese: " + err)
    s = set()
    for r in rows:
        s.add(((r.get("U") or "").strip(), (r.get("UT") or "").strip(),
               (r.get("P") or "").strip(), (r.get("R") or "").strip(),
               (r.get("F") or "").strip()))
    return s


def obj_grant_present(privs, jog, obj, kapo_tipus, kapo):
    return any(p[0] == kapo and p[1] == KAPO_TIPUS[kapo_tipus]
               and p[2] == JOG_BETU[jog] and p[3] == obj for p in privs)


def olvas_kihagy(cfg):
    import configparser
    c = configparser.ConfigParser()
    if cfg.loaded_from:
        try:
            c.read(cfg.loaded_from, encoding="utf-8")
        except TypeError:
            c.read(cfg.loaded_from)
    raw = c.get("olvas", "kihagy", fallback="") if c.has_section("olvas") \
        else ""
    items = [x.strip().upper() for x in raw.split(",") if x.strip()]
    return tuple(items) if items else OLVAS_KIHAGY


# ===========================================================================
# terv / letrehoz
# ===========================================================================

def build_grants(cfg, tables, kihagy):
    olvas, vip = cfg.user("olvas"), cfg.user("vip")
    sql = []
    for t in tables:
        if t in kihagy or not IDENT.match(t):
            continue
        sql.append("GRANT SELECT ON {0} TO {1};".format(t, olvas))
    for t in VIP_SELECT:
        sql.append("GRANT SELECT ON {0} TO {1};".format(t, vip))
    for t in VIP_INSERT:
        sql.append("GRANT INSERT ON {0} TO {1};".format(t, vip))
    sql.append("GRANT UPDATE ({0}) ON KARTYATORZS TO {1};".format(
        ", ".join(VIP_UPDATE_COLS), vip))
    return sql


def obj_grant_sql(jog, otip, obj, ktip, kapo, revoke=False):
    on = ("PROCEDURE " + obj) if otip == "PROCEDURE" else obj
    if revoke:
        return "REVOKE {0} ON {1} FROM {2} {3};".format(jog, on, ktip, kapo)
    return "GRANT {0} ON {1} TO {2} {3};".format(jog, on, ktip, kapo)


def cmd_terv(cfg, args):
    print("== gsec (a SYSDBA jelszo kornyezeti valtozoban megy, nem a "
          "parancssorban)")
    for key in ("olvas", "vip"):
        print("  gsec -add {0} -pw ********".format(cfg.user(key)))
    print("\n== GRANT (SYSDBA-kent, egy isql futasban, COMMIT-tal)")
    kihagy = olvas_kihagy(cfg)
    try:
        tables = user_tables(cfg)
        print("  -- PEPPER_OLVAS: SELECT {0} tablara (kihagyva: {1})".format(
            len([t for t in tables if t not in kihagy]), ", ".join(kihagy)))
    except Exception as e:
        tables = []
        print("  -- (tablalista nem elerheto: {0})".format(e))
        print("  -- PEPPER_OLVAS: SELECT minden tablara, kiveve: " +
              ", ".join(kihagy))
    for s in build_grants(cfg, [], kihagy):
        print("  " + s)
    for g in OBJEKTUM_JOGOK:
        print("  " + obj_grant_sql(*g))
    print("\n== Ellenorzes utana: lasd 'ellenoriz'")


def gsec(cfg, args):
    """
    gsec hivas TCP-n at (-database localhost:...admin.ib).

    MIERT: kapcsolo nelkul a gsec helyi (nem halozati) kapcsolattal nyitja
    a biztonsagi adatbazist, ami ujabb Windowson a szolgaltataskent futo
    InterBase-szel nem mukodik: "unavailable database" (elesben igy jart,
    Szentkiralyi, IB 7.5). Az isql/gbak ezert is localhost:-on megy.

    Ha a kornyezeti valtozos hitelesitest ez a verzio nem ismeri, egyszer
    ujraprobalja explicit -user/-password kapcsoloval.
    """
    sec = cfg.security_db_path()
    if sec:
        args = ["-database", "localhost:" + sec] + list(args)
    rc, out, err = run_tool(cfg, "gsec.exe" if is_windows() else "gsec", args)
    text = (out + "\n" + err).lower()
    auth_failed = ("user name and password" in text
                   or "not authorized" in text
                   or "unable to perform" in text)
    if auth_failed and "-user" not in args:
        log("  gsec: a kornyezeti valtozos hitelesites nem ment, "
            "ujraprobalom -user/-password kapcsoloval.")
        rc, out, err = run_tool(
            cfg, "gsec.exe" if is_windows() else "gsec",
            ["-user", cfg.user("sysdba"), "-password",
             cfg.password("sysdba")] + list(args))
    return rc, out, err


def gsec_users(out):
    """A gsec -display kimenetebol a felhasznalonevek (a fejlec es az
    elvalaszto sor utani sorok elso szava)."""
    names, after_header = [], False
    for line in out.splitlines():
        s = line.strip()
        if s.lower().startswith("user name"):
            after_header = True
            continue
        if not after_header or not s or set(s) <= set("-= "):
            continue
        w = s.split()[0]
        if re.match(r"^[A-Za-z0-9_$]+$", w):
            names.append(w.upper())
    return names


def gsec_preflight(cfg):
    """
    Eleri-e a gsec a felhasznalolistat? Ha nem, semmit nem probalunk.

    Az elerhetoseg jele: van fejlec ("user name ...") es nincs hiba. A
    SYSDBA-t NEM varjuk el a listaban - az IB 7.5 elesben nem mutatta.
    """
    sec = cfg.security_db_path()
    log("   biztonsagi adatbazis: {0}".format(
        sec or "NEM TALALOM (a gsec a sajat alapertelmezeset hasznalja)"))
    rc, out, err = gsec(cfg, ["-display"])
    # A listat kimenettol fuggetlenul keressuk: nem biztos, hogy minden
    # gsec-verzio a stdout-ra irja. Hiba csak a valodi hibaszoveg.
    both = out + "\n" + err
    hiba = re.search(r"unavailable|not defined|unable|error|failed|denied",
                     both, re.I)
    if "user name" in both.lower() and not hiba:
        users = gsec_users(both)
        log("   gsec: a felhasznalolista elerheto ({0} felhasznalo, SYSDBA a "
            "listaban: {1})".format(len(users), "igen" if "SYSDBA" in users
                                    else "nem"))
        return
    msg = (err or out).strip().splitlines()
    sys.exit("HIBA: a gsec nem eri el a felhasznalolistat: {0}\n"
             "Ellenorizd, hol van az admin.ib (IB 7.x) vagy isc4.gdb (IB6), "
             "es add meg a pepper_agent.ini-ben:\n"
             "  [interbase]\n  security_db = C:\\...\\admin.ib\n"
             "Semmi nem valtozott.".format(msg[0] if msg else "?"))


def gsec_user_exists(cfg, name):
    rc, out, err = gsec(cfg, ["-display", name])
    return name.upper() in gsec_users(out + "\n" + err)


def cmd_letrehoz(cfg, args):
    for key in ("sysdba", "olvas", "vip"):
        cfg.password(key)          # ConfigError, ha hianyzik

    log("1. Felhasznalok (gsec)")
    gsec_preflight(cfg)
    for key in ("olvas", "vip"):
        name = cfg.user(key)
        existed = gsec_user_exists(cfg, name)
        if existed:
            rc, out, err = gsec(cfg, ["-modify", name, "-pw",
                                      cfg.password(key)])
        else:
            rc, out, err = gsec(cfg, ["-add", name, "-pw", cfg.password(key)])
        if err.strip():
            log("   gsec uzenet: " + err.strip().splitlines()[0])
        # Csak a visszaolvasas utan mondjuk ki, hogy sikerult.
        if not gsec_user_exists(cfg, name):
            sys.exit("HIBA: {0} nem latszik a gsec -display kimeneteben. "
                     "Leallok, jogot nem adok.".format(name))
        log("   {0}: {1}".format(name, "mar letezett, jelszo frissitve"
                                 if existed else "letrehozva"))

    log("2. Kapcsolat-proba az uj felhasznalokkal")
    for key in ("olvas", "vip"):
        rows, err = q(cfg, "SELECT 1 AS X FROM RDB$DATABASE;", ["X"], key)
        if not rows or rows[0].get("X") != "1":
            sys.exit("HIBA: {0} nem tud csatlakozni.\n{1}".format(
                cfg.user(key), err))
        log("   {0}: OK".format(cfg.user(key)))

    log("3. Jogok (GRANT)")
    elotte = privileges(cfg)
    kihagy = olvas_kihagy(cfg)
    tables = user_tables(cfg)
    for t in VIP_SELECT + VIP_INSERT:
        if t not in tables:
            sys.exit("HIBA: a(z) {0} tabla nem letezik - ez nem az a "
                     "NovoHost, amire a script keszult.".format(t))
    sql = build_grants(cfg, tables, kihagy)

    # Csak azt a trigger/eljaras-jogot adjuk, ami meg nincs meg, es
    # feljegyezzuk, hogy a visszavonas CSAK ezeket vegye vissza. Egy
    # korabbi futas listajat megtartjuk: ujrafuttataskor ezek mar
    # "megvoltak", de attol meg mi adtuk hozza oket.
    hozzaadott = _load_state().get("objektum_jogok_hozzaadva", [])
    for g in OBJEKTUM_JOGOK:
        jog, otip, obj, ktip, kapo = g
        if not (exists(cfg, otip, obj) and exists(cfg, ktip, kapo)):
            log("   FIGYELEM: {0} vagy {1} nem letezik - kihagyva".format(
                obj, kapo))
            continue
        if obj_grant_present(elotte, jog, obj, ktip, kapo):
            log("   mar megvolt: " + obj_grant_sql(*g))
            continue
        sql.append(obj_grant_sql(*g))
        if list(g) not in hozzaadott:
            hozzaadott.append(list(g))

    _save_state({"datum": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "objektum_jogok_hozzaadva": hozzaadott,
                 "olvas_kihagy": list(kihagy)})

    out, err = run_isql(cfg, "\n".join(sql), user_key="sysdba", commit=True)
    if err:
        log("   isql uzenet: " + err.strip().splitlines()[0])

    log("4. Ellenorzes")
    ok = verify(cfg, kihagy)
    log("KESZ." if ok else "HIBA: az ellenorzes nem ment at - lasd fent.")
    sys.exit(0 if ok else 1)


# ===========================================================================
# ellenoriz
# ===========================================================================

def _expect(cfg, key, sql, allowed, label):
    """
    A probak egyetlen sort sem erintenek (WHERE ID = -1), nem zarolnak, es
    nincs COMMIT. A jog ellenorzese mar az utasitas elokeszitesekor
    megtortenik, ezert a 0 soros UPDATE is "no permission"-t ad, ha nincs
    jog.
    """
    out, err = run_isql(cfg, sql, user_key=key)
    err = "\n".join(l for l in err.splitlines()
                    if "Rolling back work" not in l)
    denied = bool(re.search(r"no permission|-551", err, re.I))
    other = err.strip() and not denied
    if other:
        log("   ?? {0}: varatlan hiba: {1}".format(
            label, err.strip().splitlines()[0]))
        return False
    good = (not denied) == allowed
    log("   {0} {1}: {2}".format("OK" if good else "!!", label,
                                 "engedelyezett" if not denied else "tiltott"))
    return good


def verify(cfg, kihagy=None):
    kihagy = kihagy or olvas_kihagy(cfg)
    olvas, vip = "olvas", "vip"
    checks = [
        (olvas, "SELECT COUNT(*) FROM KARTYATORZS WHERE ID = -1;", True,
         "OLVAS  SELECT KARTYATORZS"),
        (olvas, "SELECT COUNT(*) FROM NYUGTAFEJ WHERE ID = -1;", True,
         "OLVAS  SELECT NYUGTAFEJ"),
        (olvas, "UPDATE KARTYATORZS SET AKT_KP = AKT_KP WHERE ID = -1;",
         False, "OLVAS  UPDATE KARTYATORZS"),
        (olvas, "DELETE FROM KARTYANAPLO WHERE ID = -1;", False,
         "OLVAS  DELETE KARTYANAPLO"),
        (vip, "SELECT COUNT(*) FROM KARTYATORZS WHERE ID = -1;", True,
         "VIP    SELECT KARTYATORZS"),
        (vip, "UPDATE KARTYATORZS SET AKT_KP = AKT_KP, LIMIT_KP = LIMIT_KP, "
              "AKT_FORG = AKT_FORG WHERE ID = -1;", True,
         "VIP    UPDATE egyenleg-oszlopok"),
        (vip, "UPDATE KARTYATORZS SET NEV = NEV WHERE ID = -1;", False,
         "VIP    UPDATE KARTYATORZS.NEV"),
        (vip, "UPDATE KARTYATORZS SET AKT_HITEL = AKT_HITEL WHERE ID = -1;",
         False, "VIP    UPDATE KARTYATORZS.AKT_HITEL"),
        (vip, "DELETE FROM KARTYATORZS WHERE ID = -1;", False,
         "VIP    DELETE KARTYATORZS"),
        (vip, "DELETE FROM KARTYANAPLO WHERE ID = -1;", False,
         "VIP    DELETE KARTYANAPLO"),
        (vip, "UPDATE KARTYANAPLO SET OSSZEG = OSSZEG WHERE ID = -1;", False,
         "VIP    UPDATE KARTYANAPLO"),
        (vip, "SELECT COUNT(*) FROM NYUGTAFEJ WHERE ID = -1;", False,
         "VIP    SELECT NYUGTAFEJ"),
        (vip, "SELECT COUNT(*) FROM KARTYATULAJDONOS WHERE ID = -1;", False,
         "VIP    SELECT KARTYATULAJDONOS"),
    ]
    for t in kihagy:
        if IDENT.match(t):
            checks.append((olvas, "SELECT COUNT(*) FROM {0};".format(t),
                           False, "OLVAS  SELECT {0} (kihagyott)".format(t)))
    ok = True
    for key, sql, allowed, label in checks:
        ok = _expect(cfg, key, sql, allowed, label) and ok

    # Az INSERT jogot nem probaljuk ki elesben (egy probasor lefoglalna
    # egy ID-t, es a POS sajat beszurasa varhatna ra). A jogtablabol
    # igazoljuk - ez is uj kapcsolatbol olvasott tenyadat.
    privs = privileges(cfg)
    for t in VIP_INSERT:
        has = any(p[0] == cfg.user("vip") and p[2] == "I" and p[3] == t
                  for p in privs)
        log("   {0} VIP    INSERT {1}: {2}".format(
            "OK" if has else "!!", t, "megvan" if has else "HIANYZIK"))
        ok = ok and has
    bad = [p for p in privs if p[0] in (cfg.user("olvas"), cfg.user("vip"))
           and p[2] in ("D", "R")]
    if bad:
        log("   !! varatlan DELETE/REFERENCES jog: {0}".format(bad))
        ok = False
    return ok


def trigger_proba(cfg, kid):
    """
    Valodi UPDATE egy TESZTKARTYAN, ertekvaltozas nelkul, COMMIT nelkul.
    A 0 soros probak (WHERE ID = -1) a triggereket nem futtatjak le; ez
    igen (BU0, CHECK_54 ...). Ha egy triggernek hianyzik a joga, itt
    derul ki, nem az elso eles feltoltesnel. A sort a futas idejere
    zarolja (ezredmasodpercek), a QUIT visszagorgeti.
    """
    rows, err = q(cfg, "SELECT COUNT(*) AS N FROM KARTYATORZS WHERE ID = {0} "
                  "AND NEV STARTING WITH 'Minta';".format(int(kid)), ["N"])
    if not rows or rows[0].get("N") != "1":
        log("   !! a(z) {0} nem tesztkartya (a neve nem 'Minta...') - a "
            "probat nem futtatom.".format(kid))
        return False
    return _expect(cfg, "vip",
                   "UPDATE KARTYATORZS SET AKT_KP = AKT_KP, LIMIT_KP = "
                   "LIMIT_KP, AKT_FORG = AKT_FORG WHERE ID = {0};".format(
                       int(kid)), True,
                   "VIP    valodi UPDATE a {0}-es tesztkartyan, triggerekkel "
                   "(visszagorgetve)".format(kid))


def cmd_ellenoriz(cfg, args):
    ok = verify(cfg)
    if args.triggerproba:
        ok = trigger_proba(cfg, args.triggerproba) and ok
    log("Minden rendben." if ok else "VAN ELTERES - lasd fent.")
    sys.exit(0 if ok else 1)


# ===========================================================================
# visszavon
# ===========================================================================

def cmd_visszavon(cfg, args):
    if not args.igen:
        sys.exit("Ez minden PEPPER_* jogot visszavon es torli a ket "
                 "felhasznalot.\nHa biztos vagy benne:  python setup_users.py "
                 "visszavon --igen")
    privs = privileges(cfg)
    sql = []
    for key in ("olvas", "vip"):
        name = cfg.user(key)
        tabs = sorted(set(p[3] for p in privs if p[0] == name))
        for t in tabs:
            if IDENT.match(t):
                sql.append("REVOKE ALL ON {0} FROM {1};".format(t, name))
    st = _load_state()
    for g in st.get("objektum_jogok_hozzaadva", []):
        sql.append(obj_grant_sql(*g, revoke=True))
    if sql:
        out, err = run_isql(cfg, "\n".join(sql), user_key="sysdba",
                            commit=True)
        if err:
            log("isql uzenet: " + err.strip().splitlines()[0])
    left = [p for p in privileges(cfg)
            if p[0] in (cfg.user("olvas"), cfg.user("vip"))]
    log("Megmaradt PEPPER_* jog: {0}".format(len(left)))
    for key in ("olvas", "vip"):
        gsec(cfg, ["-delete", cfg.user(key)])
        log("{0}: {1}".format(cfg.user(key), "MEG LETEZIK" if
                              gsec_user_exists(cfg, cfg.user(key))
                              else "torolve"))
    if os.path.exists(ALLAPOT):
        os.rename(ALLAPOT, ALLAPOT + ".visszavonva")


# ===========================================================================

def _save_state(d):
    with open(ALLAPOT, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def _load_state():
    if not os.path.exists(ALLAPOT):
        return {}
    with open(ALLAPOT, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("lepes", choices=["titkosit", "jelszo", "terv",
                                      "letrehoz", "ellenoriz", "visszavon"])
    ap.add_argument("--igen", action="store_true",
                    help="visszavonas megerositese")
    ap.add_argument("--triggerproba", type=int, metavar="KARTYA_ID",
                    help="ellenoriz: valodi, visszagorgetett UPDATE ezen a "
                         "tesztkartyan (a neve 'Minta'-val kell kezdodjon)")
    args = ap.parse_args()
    set_log(os.path.join(HERE, "setup_users_log.txt"))
    log("setup_users {0} - verzio {1}".format(args.lepes, AGENT_VERSION))
    cfg = load_config()
    try:
        {"titkosit": cmd_titkosit, "jelszo": cmd_jelszo, "terv": cmd_terv,
         "letrehoz": cmd_letrehoz,
         "ellenoriz": cmd_ellenoriz,
         "visszavon": cmd_visszavon}[args.lepes](cfg, args)
    except ConfigError as e:
        sys.exit("HIBA: {0}".format(e))


if __name__ == "__main__":
    main()
