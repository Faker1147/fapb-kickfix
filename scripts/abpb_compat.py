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

Supported builds
----------------
Every build is pinned by its pristine and patched SHA-256.  Unknown builds are
refused on purpose; add a new entry to ``BUILDS`` after verifying the offsets.

    ABPB 4.3.3-abpb.1   FF61716F...CD776 -> 675A62AD...669ED
    ABPB 4.3.3-abpb.2   6CE76D06...ABBD  -> F2750780...A254D

The patcher can --revert and --dry-run.
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

# Each build uses the same 22-byte transformation, but the file offsets moved
# between abpb.1 and abpb.2.  Keep the replacement order: quota string first,
# then version string (both are 11 bytes apart in .rdata).
BUILDS = {
    "ff61716f5eb77d17e27d9dc3e696b0944cad1c17ce3a520828e37fab226cd776": {
        "label": "ABPB 4.3.3-abpb.1 Windows x86",
        "patched": "675a62ad455240c41c50cd2207519c7367a1b7b1043656d9e4d664bff92669ed",
        "edits": [
            (0x27D834, b"fapb_quota",   b"fb_quota\0\0",   "name: fapb_quota -> fb_quota"),
            (0x27D77C, struct.pack("<I", 0x0A), struct.pack("<I", 0x08), "len: 10 -> 8"),
            (0x27D83F, b"fapb_version", b"fb_version\0\0", "name: fapb_version -> fb_version"),
            (0x27D784, struct.pack("<I", 0x0C), struct.pack("<I", 0x0A), "len: 12 -> 10"),
        ],
    },
    "6ce76d06fcfd3198b1d213bb2576dcceaec432c990cd7cdbf00688df5e26abbd": {
        "label": "ABPB 4.3.3-abpb.2 Windows x86",
        "patched": "f2750780b14655126f0142d691c6ae5c362eaefa12a9e8a216f082d1e80a254d",
        "edits": [
            (0x27D8F4, b"fapb_quota",   b"fb_quota\0\0",   "name: fapb_quota -> fb_quota"),
            (0x27D83C, struct.pack("<I", 0x0A), struct.pack("<I", 0x08), "len: 10 -> 8"),
            (0x27D8FF, b"fapb_version", b"fb_version\0\0", "name: fapb_version -> fb_version"),
            (0x27D844, struct.pack("<I", 0x0C), struct.pack("<I", 0x0A), "len: 12 -> 10"),
        ],
    },
}

PATCHED_TO_PRISTINE = {v["patched"]: k for k, v in BUILDS.items()}

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


def _guess_build(data: bytes):
    """Return (pristine_sha, build) based on file content, or (None, None)."""
    sha = sha256_bytes(data)
    if sha in BUILDS:
        return sha, BUILDS[sha]
    if sha in PATCHED_TO_PRISTINE:
        pristine = PATCHED_TO_PRISTINE[sha]
        return pristine, BUILDS[pristine]

    # Fall back to byte-level recognition (e.g. one edit partially applied).
    for pristine, build in BUILDS.items():
        old_hits = 0
        new_hits = 0
        for off, old, new, _ in build["edits"]:
            cur = data[off:off + max(len(old), len(new))]
            if cur == old:
                old_hits += 1
            elif cur == new:
                new_hits += 1
        if old_hits and new_hits:
            return pristine, build
        if new_hits == len(build["edits"]):
            return pristine, build
        if old_hits == len(build["edits"]):
            return pristine, build
    return None, None


def analyse(data: bytes) -> dict:
    pe = PE(data)
    pristine, build = _guess_build(data)
    sha = sha256_bytes(data)

    if build is None:
        return {
            "state": "unknown",
            "label": None,
            "sha256": sha,
            "problems": [
                "unsupported ABPB.dll (sha256 %s)." % sha,
                "Known builds:",
                *["  %s  %s" % (k, v["label"]) for k, v in BUILDS.items()],
                "Update BUILDS in abpb_compat.py after verifying the new offsets.",
            ],
        }

    problems = []
    patched_hits = 0
    pristine_hits = 0
    for off, old, new, what in build["edits"]:
        cur = data[off:off + max(len(old), len(new))]
        sec = section_of(pe, off)
        if sec != EXPECT_SECTION:
            problems.append("%s: offset %#x is in %s, expected %s"
                            % (what, off, sec, EXPECT_SECTION))
        if len(old) != len(new):
            problems.append("%s: replacement changes length (%d -> %d)"
                            % (what, len(old), len(new)))
        if cur[:len(new)] == new:
            patched_hits += 1
        elif cur[:len(old)] == old:
            pristine_hits += 1
        else:
            problems.append("%s: unexpected bytes %s at %#x"
                            % (what, cur.hex().upper(), off))

    n = len(build["edits"])
    if patched_hits == n and not problems:
        state = "patched"
    elif pristine_hits == n and not problems:
        state = "pristine"
    else:
        state = "unknown"

    return {
        "state": state,
        "label": build["label"],
        "pristine_sha256": pristine,
        "sha256": sha,
        "problems": problems,
    }


def apply_patch(path: str, dry_run: bool = False) -> dict:
    data = bytearray(open(path, "rb").read())
    info = analyse(bytes(data))
    if info["state"] == "patched":
        return {**info, "changed": False, "state": "already-patched"}
    if info["state"] != "pristine" or info["problems"]:
        raise ValueError("refusing to patch:\n  " + "\n  ".join(info["problems"]))
    build = BUILDS[info["pristine_sha256"]]
    if dry_run:
        return {**info, "changed": True, "state": "would-patch"}
    for off, old, new, what in build["edits"]:
        if bytes(data[off:off + len(old)]) != old:
            raise RuntimeError("pre-flight check failed for %s at %#x" % (what, off))
        data[off:off + len(new)] = new
    tmp = path + ".tmp"
    open(tmp, "wb").write(bytes(data))
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    out = analyse(bytes(data))
    if out["state"] != "patched":
        raise RuntimeError("post-patch verification failed: %s" % out)
    return {"changed": True, **out, "state": "patched"}


def revert_patch(path: str) -> dict:
    data = bytearray(open(path, "rb").read())
    info = analyse(bytes(data))
    if info["state"] == "pristine":
        return {**info, "changed": False, "state": "already-pristine"}
    if info["state"] != "patched" or info["problems"]:
        raise ValueError("cannot revert: file is not in a known patched state (%s)"
                         % info["state"])
    build = BUILDS[info["pristine_sha256"]]
    for off, old, new, what in build["edits"]:
        if bytes(data[off:off + len(new)]) != new:
            raise RuntimeError("pre-flight check failed for %s at %#x" % (what, off))
        data[off:off + len(old)] = old
    tmp = path + ".tmp"
    open(tmp, "wb").write(bytes(data))
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    out = analyse(bytes(data))
    if out["state"] != "pristine":
        raise RuntimeError("post-revert verification failed: %s" % out)
    return {"changed": True, **out, "state": "reverted"}


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
        print("build    : %s" % res.get("label", "unknown"))
        print("state    : %s" % res.get("state"))
        if "sha256" in res:
            print("sha256   : %s" % res["sha256"])
        for p in res.get("problems", []):
            print("problem  : %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
