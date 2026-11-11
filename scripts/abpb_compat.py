#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
abpb_compat.py - make ABPB's "other bot" guard recognise FAPB.

Background
----------
ABPB (AiBo 4.3.3 fork) disables its own bot quota when it sees another bot
system at map start.  It looks for these cvar names (plain ASCII, in .rdata):

    yb_quota yb_version yapb_quota yapb_version sypb_quota sypb_version
    fapb_quota fapb_version ebot_quota ebot_version cs_ebot_quota
    podbot_quota podbot_version pb_quota pb_version zbot_quota zbot_version
    zb_quota zb_version realbot_quota realbot_version

Each name sits in an 8-byte {const char *name; uint32 len;} entry, e.g.

    0x27D778: 0x1027EE34 "fapb_quota"   0x27D77C: 0x0000000A (len 10)

But FAPB 1.6 (renamed YaPB 2.55b) registers its cvars as ``fb_*``, not
``fapb_*``: it has ``fb_quota`` and ``fb_version``.  ABPB therefore never
detects FAPB, both managers stay enabled, and the server can run out of
edicts / crash.

Fix
---
Rewrite those two entries in place so the guard looks for the names FAPB
actually has.  Same-or-shorter length, no size change, no relocation touched:

    "fapb_quota"   (len 10) -> "fb_quota"   + NUL NUL (len 8)
    "fapb_version" (len 12) -> "fb_version" + NUL NUL (len 10)

Only these 4 spots are modified (2 strings + 2 length dwords).

The patcher is pinned to the ABPB 4.3.3 build from the official zip
(SHA-256 ff61716f...), refuses to touch anything else, and can --revert.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fapb_patch import PE  # noqa: E402  (shared PE header helper)

DLL_REL = os.path.join("cstrike", "addons", "ABPB", "bin", "ABPB.dll")

SHA256_PRISTINE = "ff61716f5eb77d17e27d9dc3e696b0944cad1c17ce3a520828e37fab226cd776"

# (file offset, old bytes, new bytes, what)
EDITS = [
    (0x27D834, b"fapb_quota",   b"fb_quota\0\0",   "name: fapb_quota -> fb_quota"),
    (0x27D77C, struct.pack("<I", 0x0A), struct.pack("<I", 0x08), "len: 10 -> 8"),
    (0x27D83F, b"fapb_version", b"fb_version\0\0", "name: fapb_version -> fb_version"),
    (0x27D784, struct.pack("<I", 0x0C), struct.pack("<I", 0x0A), "len: 12 -> 10"),
]

# sanity: entries live in .rdata
EXPECT_SECTION = ".rdata"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def find_dll(game_dir: str) -> str:
    p = os.path.join(game_dir, DLL_REL)
    if os.path.isfile(p):
        return p
    alt = os.path.join(game_dir, "addons", "ABPB", "bin", "ABPB.dll")
    if os.path.isfile(alt):
        return alt
    raise FileNotFoundError(
        "ABPB.dll not found under %s (expected cstrike\\addons\\ABPB\\bin\\ABPB.dll)"
        % game_dir)


def section_of(pe: PE, off: int):
    for name, va, vs, ra, rs in pe.sections:
        if ra <= off < ra + rs:
            return name
    return None


def analyse(data: bytes) -> dict:
    pe = PE(data)
    state = "pristine"
    problems = []
    for off, old, new, what in EDITS:
        cur = data[off:off + len(old)]
        sec = section_of(pe, off)
        if sec != EXPECT_SECTION:
            problems.append("%s: offset %#x is in %s, expected %s"
                            % (what, off, sec, EXPECT_SECTION))
        if cur == new:
            continue
        if cur != old:
            state = "unknown"
            problems.append("%s: unexpected bytes %s at %#x"
                            % (what, cur.hex().upper(), off))
            continue
        state = "pristine" if state != "unknown" else state
    if state == "pristine" and problems:
        state = "unknown"
    if state == "pristine":
        if all(data[off:off + len(new)] == new for off, old, new, _ in EDITS):
            state = "patched"
    return {"state": state, "problems": problems, "sha256": sha256_bytes(data)}


def apply_patch(path: str, dry_run: bool = False) -> dict:
    data = bytearray(open(path, "rb").read())
    info = analyse(bytes(data))
    if info["state"] == "patched":
        return {**info, "changed": False, "state": "already-patched"}
    if info["problems"]:
        raise ValueError("refusing to patch:\n  " + "\n  ".join(info["problems"]))
    if info["sha256"] != SHA256_PRISTINE:
        raise ValueError(
            "unexpected ABPB.dll (sha256 %s, expected %s).\n"
            "This build is not the ABPB 4.3.3 package this patch was written for."
            % (info["sha256"], SHA256_PRISTINE))
    if dry_run:
        return {**info, "changed": True, "state": "would-patch"}
    for off, old, new, what in EDITS:
        data[off:off + len(new)] = new
    tmp = path + ".tmp"
    open(tmp, "wb").write(bytes(data))
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    out = analyse(bytes(data))
    if out["state"] != "patched":
        raise RuntimeError("post-patch verification failed: %s" % out)
    return {"changed": True, "state": "patched", "sha256": out["sha256"]}


def revert_patch(path: str) -> dict:
    data = bytearray(open(path, "rb").read())
    info = analyse(bytes(data))
    if info["state"] == "pristine":
        return {**info, "changed": False, "state": "already-pristine"}
    if info["state"] != "patched":
        raise ValueError("cannot revert: file is not in a known patched state (%s)"
                         % info["state"])
    for off, old, new, what in EDITS:
        data[off:off + len(new)] = old
    tmp = path + ".tmp"
    open(tmp, "wb").write(bytes(data))
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    out = analyse(bytes(data))
    return {"changed": True, "state": "reverted", "sha256": out["sha256"]}


def report(path: str) -> dict:
    data = open(path, "rb").read()
    info = analyse(data)
    return {"dll": path, **info}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Patch ABPB.dll so its compat guard sees FAPB (fb_* cvars)")
    ap.add_argument("--game-dir", default=os.environ.get("FAPB_GAME_DIR", ""),
                    help="CS 1.6 root folder (contains hl.exe)")
    ap.add_argument("--dll", default="", help="explicit path to ABPB.dll")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        dll = a.dll or find_dll(a.game_dir)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    try:
        if a.apply or a.dry_run:
            res = apply_patch(dll, dry_run=a.dry_run)
        elif a.revert:
            res = revert_patch(dll)
        else:
            res = report(dll)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 3

    res.setdefault("dll", dll)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("ABPB.dll : %s" % dll)
        print("state    : %s" % res.get("state"))
        if "sha256" in res:
            print("sha256   : %s" % res["sha256"])
        for p in res.get("problems", []):
            print("problem  : %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
