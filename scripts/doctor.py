#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py - diagnose a CS 1.6 / FAPB installation.

Checks
  1. Metamod plugins.ini  -> how many bot cores are active (must be exactly one)
  2. fapb.dll             -> crash-patch state
  3. fapb.cfg             -> obviously out-of-range values
  4. WER crash dumps      -> confirm the 0x18173 signature

Exit code 0 = healthy, 1 = problems found, 2 = cannot locate the game.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fapb_patch as F  # noqa: E402

BOT_CORE_RE = re.compile(
    r"^\s*win32\s+addons[\\/](yapb|sypb|podbot|ebot|csbot_enabler|fapb)[\\/]", re.I)
AMXX_RE = re.compile(r"^\s*win32\s+addons[\\/]amxmodx[\\/]dlls[\\/](amxmodx_mm|amxmodx_bl_mm)\.dll", re.I)

CVAR_CHECKS = {
    "fb_followuser": (0, 1, "0/1 或玩家序号; 99 是无效值"),
    "fb_quota": (0, 32, "0..32"),
    "fb_autovacate": (0, 1, "0/1"),
    "fb_followpercent": (0, 100, "0..100"),
    "fb_dangerfactor": (0, 10000, "0..10000"),
    "fb_minskill": (0, 100, "0..100"),
    "fb_maxskill": (0, 100, "0..100"),
    "fb_thingfps": (1, 50, "1..50"),
}


def detect_game_dir(explicit: str = "") -> str:
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("FAPB_GAME_DIR"):
        cands.append(os.environ["FAPB_GAME_DIR"])
    try:
        import winreg
        for root, path in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\CounterStrike"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\CounterStrike"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\CounterStrike"),
        ):
            try:
                with winreg.OpenKey(root, path) as k:
                    cands.append(winreg.QueryValueEx(k, "InstallPath")[0])
            except OSError:
                pass
    except ImportError:
        pass
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "hl.exe")):
            return os.path.abspath(c)
    return ""


def read_plugins_ini(game: str):
    p = os.path.join(game, "cstrike", "addons", "metamod", "plugins.ini")
    if not os.path.isfile(p):
        return p, None
    with open(p, "r", encoding="latin-1") as f:
        lines = f.read().splitlines()
    active_bot, active_amxx = [], []
    for ln in lines:
        if ln.strip().startswith(";") or ln.strip().startswith("//"):
            continue
        if BOT_CORE_RE.match(ln):
            active_bot.append(ln.strip())
        if AMXX_RE.match(ln):
            active_amxx.append(ln.strip())
    return p, (active_bot, active_amxx, lines)


def read_cfg(game: str) -> dict:
    for rel in (os.path.join("cstrike", "addons", "fapb", "config", "fapb.cfg"),):
        p = os.path.join(game, rel)
        if not os.path.isfile(p):
            continue
        out = {}
        with open(p, "r", encoding="latin-1", errors="replace") as f:
            for ln in f:
                m = re.match(r'^\s*(fb_[a-z0-9_]+)\s+"?([^"\s]*)"?', ln, re.I)
                if m:
                    out[m.group(1).lower()] = m.group(2)
        return out
    return {}


def scan_dumps(limit: int = 12):
    folder = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps")
    rows = []
    for p in sorted(glob.glob(os.path.join(folder, "hl.exe.*.dmp")))[-limit:]:
        try:
            d = open(p, "rb").read()
            nstreams, dirrva = struct.unpack_from("<II", d, 8)
            streams = {}
            for i in range(nstreams):
                t, s, r = struct.unpack_from("<III", d, dirrva + i * 12)
                streams.setdefault(t, []).append((s, r))
            if 6 not in streams or 4 not in streams:
                continue
            s, r = streams[6][0]
            eo = r + 8
            code = struct.unpack_from("<I", d, eo)[0]
            addr = struct.unpack_from("<Q", d, eo + 16)[0]
            s4, r4 = streams[4][0]
            n = struct.unpack_from("<I", d, r4)[0]
            mod = None
            for i in range(n):
                o = r4 + 4 + i * 108
                base, sz, _c, _t, nrva = struct.unpack_from("<QIIII", d, o)
                nl = struct.unpack_from("<I", d, nrva)[0]
                nm = d[nrva + 4:nrva + 4 + nl].decode("utf-16-le", "replace")
                if "fapb.dll" in nm.lower():
                    mod = (base, nm)
                    break
            rva = (addr - mod[0]) if mod else 0
            rows.append((os.path.basename(p), os.path.getmtime(p), code, rva, mod is not None))
        except Exception:
            continue
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diagnose CS 1.6 + FAPB")
    ap.add_argument("--game-dir", default="", help="CS 1.6 root folder")
    ap.add_argument("--dumps", action="store_true", help="also scan WER crash dumps")
    a = ap.parse_args(argv)

    game = detect_game_dir(a.game_dir)
    if not game:
        print("找不到 CS 1.6 目录 (hl.exe)。请用 --game-dir 指定。")
        return 2

    problems = 0
    print("游戏目录 : %s" % game)
    print()

    # 1. plugins.ini
    pini, parsed = read_plugins_ini(game)
    print("[1] Metamod 插件列表")
    print("    %s" % pini)
    if parsed is None:
        print("    !! plugins.ini 不存在")
        problems += 1
    else:
        bots, amxx, _ = parsed
        if not bots:
            print("    !! 没有启用任何 Bot 核心 (FAPB 未加载?)")
            problems += 1
        elif len(bots) == 1:
            print("    OK  只有一个 Bot 核心: %s" % bots[0])
        else:
            print("    !! 同时加载了 %d 个 Bot 核心 (FAPB 会随机/必然崩溃):" % len(bots))
            for b in bots:
                print("         - %s" % b)
            problems += 1
        for m in amxx:
            print("    AMXX: %s" % m)
        if len(amxx) > 1:
            print("    !! amxmodx_mm.dll 与 amxmodx_bl_mm.dll 同时加载")
            problems += 1
    print()

    # 2. dll
    print("[2] fapb.dll")
    try:
        dll = F.find_dll(game)
        st = F.state(dll)
        print("    %s" % dll)
        print("    state  : %s   (bytes %s @ RVA %#x)" % (st["state"], st["bytes"], F.PATCH_RVA))
        print("    sha256 : %s" % st["sha256"])
        if st["state"] == "pristine":
            print("    -> 未打补丁。踢 BOT 时仍可能闪退; 运行 install.ps1")
        elif st["state"] == "patched":
            print("    -> 已打补丁: 删除 Bot 不再访问 gpGlobals。")
        else:
            print("    !! 未知字节, 可能被其他工具改过")
            problems += 1
    except Exception as e:
        print("    !! %s" % e)
        problems += 1
    print()

    # 3. config
    print("[3] fapb.cfg 关键参数")
    cfg = read_cfg(game)
    if not cfg:
        print("    !! 读不到 fapb.cfg")
        problems += 1
    else:
        for k in ("fb_quota", "fb_autovacate", "fb_followuser", "fb_followpercent",
                  "fb_dangerfactor", "fb_minskill", "fb_maxskill", "fb_language"):
            if k in cfg:
                print("    %-18s = %s" % (k, cfg[k]))
        for k, (lo, hi, desc) in CVAR_CHECKS.items():
            if k not in cfg:
                continue
            try:
                v = float(cfg[k])
            except ValueError:
                continue
            if not (lo <= v <= hi):
                print("    !! %s = %s 超出合理范围 (%s)" % (k, cfg[k], desc))
                problems += 1
    print()

    # 4. dumps
    if a.dumps:
        print("[4] Windows 崩溃转储 (hl.exe)")
        rows = scan_dumps()
        if not rows:
            print("    (没有找到转储)")
        for name, mt, code, rva, has_fapb in rows:
            import datetime
            ts = datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S")
            mark = ""
            if has_fapb and rva == F.PATCH_RVA:
                mark = "   <-- 已知踢 BOT 崩溃点"
            print("    %s  %s  code=%#x  rva=%#x%s" % (ts, name, code, rva, mark))
        print()

    print("结论:", "一切正常" if problems == 0 else "发现 %d 个问题" % problems)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
