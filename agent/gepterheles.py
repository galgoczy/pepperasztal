# -*- coding: utf-8 -*-
"""
gepterheles.py - a gep terhelese egy jelentes-futas alatt (Windows).

Egy futas (a percenkenti feladat) elejen es vegen mintat vesz:
  - rendszer: CPU-kihasznaltsag az elozo futas vege ota, kb. egy percre
    (GetSystemTimes), memoria (GlobalMemoryStatusEx)
  - sajat: a Python-folyamat es az altala inditott isql-ek CPU-ideje
    masodpercben, es ugyanez az egesz gep (minden mag) egy percere vetitve;
    a Python memoriaja (munkakeszlet, csucs)
  - InterBase: az ibserver.exe CPU-ja es memoriaja ugyanebben az idoben
  - a legtobb CPU-t vivo folyamatok neve es szazaleka az elmult percben
    (csak a fajlnev, pl. NovoHost.exe, MsMpEng.exe - mas adat nem)

Kulso csomag nincs (ctypes). Mas rendszeren minden ertek None.
"""

import ctypes
import os
import time

from common import GYEREK_CPU

WIN = os.name == "nt"
IB_FOLYAMATOK = ("ibserver.exe",)


if WIN:
    from ctypes import wintypes

    _k32 = ctypes.windll.kernel32

    class _FT(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _MEM(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    class _PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    # Pontos tipusok: 64 bites Windowson a HANDLE 8 bajt, alapertelmezett
    # (int) atadassal csonkulna.
    _H, _D, _P = wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER
    _k32.GetCurrentProcess.restype = _H
    _k32.GetCurrentProcess.argtypes = []
    _k32.OpenProcess.restype = _H
    _k32.OpenProcess.argtypes = [_D, wintypes.BOOL, _D]
    _k32.CloseHandle.argtypes = [_H]
    _k32.GetProcessTimes.argtypes = [_H, _P(_FT), _P(_FT), _P(_FT), _P(_FT)]
    _k32.GetSystemTimes.argtypes = [_P(_FT), _P(_FT), _P(_FT)]
    _k32.GlobalMemoryStatusEx.argtypes = [_P(_MEM)]
    _k32.K32GetProcessMemoryInfo.argtypes = [_H, _P(_PMC), _D]
    _k32.CreateToolhelp32Snapshot.restype = _H
    _k32.CreateToolhelp32Snapshot.argtypes = [_D, _D]
    _k32.Process32FirstW.argtypes = [_H, _P(_PE)]
    _k32.Process32NextW.argtypes = [_H, _P(_PE)]


def _mp(ft):
    return ((ft.hi << 32) | ft.lo) / 1e7


def _rendszer():
    i, k, u = _FT(), _FT(), _FT()
    if not _k32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)):
        return None
    return _mp(i), _mp(k), _mp(u)


def _proc_cpu(h):
    a, b, k, u = _FT(), _FT(), _FT(), _FT()
    if not _k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                                ctypes.byref(k), ctypes.byref(u)):
        return None
    return _mp(k) + _mp(u)


def _proc_mem(h):
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return None, None
    return pmc.WorkingSetSize / 1048576.0, pmc.PeakWorkingSetSize / 1048576.0


def _ib_folyamatok():
    """{pid: (cpu_mp, mem_mb)} az ibserver.exe-kre."""
    ki = {}
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return ki
    try:
        pe = _PE()
        pe.dwSize = ctypes.sizeof(_PE)
        ok = _k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower() in IB_FOLYAMATOK:
                h = _k32.OpenProcess(0x1000, False, pe.th32ProcessID)
                if h:
                    try:
                        ki[pe.th32ProcessID] = (_proc_cpu(h), _proc_mem(h)[0])
                    finally:
                        _k32.CloseHandle(h)
            ok = _k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        _k32.CloseHandle(snap)
    return ki


def _osszes_folyamat():
    """{pid: [nev, cpu_mp]} minden folyamatra, amit meg tudunk nyitni
    (SYSTEM-kent szinte mindet). Csak a futtathato fajl neve, mas nem."""
    ki = {}
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return ki
    try:
        pe = _PE()
        pe.dwSize = ctypes.sizeof(_PE)
        ok = _k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            pid = pe.th32ProcessID
            if pid:
                h = _k32.OpenProcess(0x1000, False, pid)
                if h:
                    try:
                        cpu = _proc_cpu(h)
                        if cpu is not None:
                            ki[str(pid)] = [pe.szExeFile[:60], round(cpu, 2)]
                    finally:
                        _k32.CloseHandle(h)
            ok = _k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        _k32.CloseHandle(snap)
    return ki


def _minta():
    if not WIN:
        return None
    try:
        return {"t": time.time(), "rendszer": _rendszer(),
                "sajat": _proc_cpu(_k32.GetCurrentProcess()),
                "gyerek": GYEREK_CPU[0], "ib": _ib_folyamatok(),
                "proc": _osszes_folyamat()}
    except Exception:
        return None


class Meres(object):
    """
    elozo: az elozo futas vegen mentett nyers rendszer-ido (gep_allapot.json
    'nyers' mezoje). Ebbol a gep CPU-ja az elozo futas vege ota - tehat kb.
    egy teljes percre - szamolhato, nem csak a mi futasunk par masodpercere
    (az felfele torzitana, mert benne van a sajat terhelesunk).
    """

    def __init__(self, elozo=None):
        self.eleje = _minta()
        self.elozo = elozo if isinstance(elozo, dict) else None

    def eredmeny(self):
        """Az inditas ota eltelt idore. Hiba eseten None."""
        if not WIN or not self.eleje:
            return None
        try:
            v = _minta()
            e = self.eleje
            ido = max(0.001, v["t"] - e["t"])
            ncpu = os.cpu_count() or 1
            ki = {"ido_mp": round(ido, 1), "cpu_db": ncpu}
            # A gep CPU-ja: az elozo futas vege ota (kb. 1 perc), ha van ilyen
            # minta es nem regebbi 5 percnel; kulonben csak a futas alatt.
            kezdet = e["rendszer"]
            ablak = ido
            el = self.elozo or {}
            if (el.get("rendszer") and el.get("t")
                    and 0 < v["t"] - el["t"] < 300):
                kezdet, ablak = el["rendszer"], v["t"] - el["t"]
            if kezdet and v["rendszer"]:
                di = v["rendszer"][0] - kezdet[0]
                dk = v["rendszer"][1] - kezdet[1]
                du = v["rendszer"][2] - kezdet[2]
                ossz = dk + du       # a kernel-ido az ures idot is tartalmazza
                if ossz > 0:
                    ki["cpu_rendszer"] = round(100.0 * (ossz - di) / ossz, 1)
                    ki["cpu_ablak_mp"] = round(ablak, 1)
            # Az ugynok: CPU-masodperc ebben a futasban, es ugyanez az egesz
            # gep (minden mag) egy percere vetitve - a feladat percenkent fut.
            sajat = (v["sajat"] or 0) - (e["sajat"] or 0) + v["gyerek"] - e["gyerek"]
            ki["sajat_cpu_mp"] = round(sajat, 2)
            ki["sajat_cpu"] = round(100.0 * sajat / (60.0 * ncpu), 2)
            m = _MEM()
            m.dwLength = ctypes.sizeof(_MEM)
            if _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
                ki["mem_terheles"] = int(m.dwMemoryLoad)
                ki["mem_ossz_mb"] = int(m.ullTotalPhys / 1048576)
                ki["mem_szabad_mb"] = int(m.ullAvailPhys / 1048576)
            ws, csucs = _proc_mem(_k32.GetCurrentProcess())
            if ws is not None:
                ki["sajat_mem_mb"] = round(ws, 1)
                ki["sajat_mem_csucs_mb"] = round(csucs, 1)
            ib_cpu, ib_mem = 0.0, 0.0
            for pid, (cpu, mem) in v["ib"].items():
                if pid in e["ib"] and cpu is not None and e["ib"][pid][0] is not None:
                    ib_cpu += cpu - e["ib"][pid][0]
                ib_mem += mem or 0
            if v["ib"]:
                ki["ib_cpu"] = round(100.0 * ib_cpu / (ido * ncpu), 2)
                ki["ib_mem_mb"] = round(ib_mem, 1)
            # A legtobb CPU-t vivo folyamatok az elozo futas vege ota (kb. 1
            # perc): nev es szazalek az egesz gepbol. A rovid eletu, kozben
            # indult-leallt folyamatok kimaradnak.
            if el.get("proc") and el.get("t") and 0 < v["t"] - el["t"] < 300:
                per = (v["t"] - el["t"]) * ncpu
                elott = el["proc"]
                csop = {}
                for pid, (nev, cpu) in v["proc"].items():
                    regi = elott.get(pid)
                    if regi and regi[0] == nev and cpu >= regi[1]:
                        csop[nev] = csop.get(nev, 0.0) + cpu - regi[1]
                top = sorted(csop.items(), key=lambda x: -x[1])[:6]
                ki["top"] = [[n, round(100.0 * c / per, 1)] for n, c in top
                             if 100.0 * c / per >= 0.2]
            ki["ido"] = time.strftime("%Y-%m-%d %H:%M:%S")
            ki["nyers"] = {"t": v["t"], "rendszer": v["rendszer"], "proc": v["proc"]}
            return ki
        except Exception as ex:
            return {"hiba": str(ex)[:160]}
