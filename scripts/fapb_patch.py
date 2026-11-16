#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fapb_patch.py - inspect / revert the legacy 5-byte FAPB kick-crash patch.

Status: DEPRECATED
------------------
1.2.0 replaces the workaround with a rebuilt DLL (scripts/fapb_rebuild.py).
The released FAPB 1.6 DLL has a broken import table (see
docs/fapb-dll-repair.md); patching one instruction only hides one symptom.

    released DLL  (606E7A6A...3553) + 5-byte patch -> 18E536C0...2152
    rebuilt DLL   (9AFDAA67...8C96) + 5-byte patch -> 9F2EBB5A...1CAD
                                                    ^^^^^^^^^^^^^^^^^
                                                    DO NOT USE: crashes on kick

The rebuilt DLL must stay UNPATCHED.  This tool refuses to apply the
5-byte patch to it; --revert is still allowed (and recommended) if an old
run already patched it.

What the old patch did
----------------------
    CBot::~CBot() releases the bot's name slot:

        1001811D  A1 DC350B10     mov  eax, [0x100B35DC]   ; registry count
        10018122  33F6            xor  esi, esi
        10018124  85C0            test eax, eax
        10018126  0F84B4000000    je   0x100181E0          ; no names -> done
        10018130  ...             ; for each name:
        10018161  8B9794040000    mov  edx, [edi+0x494]    ; m_pEdict
        10018167  8B82D0010000    mov  eax, [edx+0x1D0]    ; v.netname
        1001816D  8B1548350B10    mov  edx, [0x100B3548]   ; gpGlobals
        10018173  038298000000    add  eax, [edx+0x98]     ; <-- crash
        10018180  ...             ; strcmp(...)

The patch turned the first instruction into an unconditional jump:

    1001811D  A1 DC350B10   mov eax,[0x100B35DC]
  ->1001811D  E9 BE000000   jmp 0x100181E0

On the released DLL this happened to stop the kick crash, but the
underlying heap corruption remained.  On the rebuilt DLL it is actively
harmful: bot removal crashes in hl.exe (EIP 0x005381E0, stack shows
~CBot at fapb+0x18838) because the destructor's member teardown expects
the name-release path to have run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys

DLL_REL = os.path.join("cstrike", "addons", "fapb", "dlls", "fapb.dll")

# --- identity ---------------------------------------------------------------
SHA256_RELEASED = "606e7a6ab8793553847bcbf2d5665d29edea0b3529eaca537d7e76de7b6e3553"
SHA256_RELEASED_PATCHED = "18e536c00cc58573f3d4d0a803aedc9b4d0e4993654612e62b7c48b756762152"
SHA256_REBUILT = "9afdaa6796e59026bdd65425a29ab46429aee11d9fee1205ff05351b2dd08c96"
SHA256_REBUILT_PATCHED = "9f2ebb5a9747c2cafb0e12ab189b017acbc0c22f4ff2ede243fed43733a01cad"

PATCH_RVA = 0x1811D
PATCH_ORIG = bytes.fromhex("A1DC350B10")          # mov eax, [0x100B35DC]
PATCH_NEW = bytes.fromhex("E9BE000000")           # jmp 0x100181E0
JUMP_TARGET = 0x100181E0

KNOWN = {
    SHA256_RELEASED: "released",
    SHA256_RELEASED_PATCHED: "released-legacy-patched",
    SHA256_REBUILT: "rebuilt",
    SHA256_REBUILT_PATCHED: "rebuilt-legacy-patched",
}


# --- PE helpers -------------------------------------------------------------
class PE:
    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE file (missing MZ)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file (missing PE signature)")
        self.pe = pe
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        optsz = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        self.magic = struct.unpack_from("<H", data, opt)[0]
        self.imagebase = struct.unpack_from("<I", data, opt + 28)[0]
        self.sizeofimage = struct.unpack_from("<I", data, opt + 56)[0]
        sec = opt + optsz
        self.sections = []
        for i in range(nsec):
            o = sec + i * 40
            name = data[o:o + 8].rstrip(b"\0").decode("latin-1", "replace")
            vs, va, rs, ra = struct.unpack_from("<IIII", data, o + 8)
            self.sections.append((name, va, vs, ra, rs))

    def rva_to_off(self, rva: int):
        for name, va, vs, ra, rs in self.sections:
            if va <= rva < va + max(vs, rs):
                if rs == 0:
                    return None
                return ra + (rva - va)
        return None

    def text(self):
        for s in self.sections:
            if s[0] == ".text":
                return s
        return None

    def has_section(self, name: str) -> bool:
        return any(s[0] == name for s in self.sections)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_dll(game_dir: str) -> str:
    p = os.path.join(game_dir, DLL_REL)
    if os.path.isfile(p):
        return p
    alt = os.path.join(game_dir, "addons", "fapb", "dlls", "fapb.dll")
    if os.path.isfile(alt):
        return alt
    raise FileNotFoundError("fapb.dll not found under %s" % game_dir)


def branch_targets(data: bytes, text_sec):
    """Yield (rva, target) for every direct rel32 jump/call in .text."""
    name, va, vs, ra, rs = text_sec
    blob = data[ra:ra + rs]
    out = []
    i = 0
    n = len(blob)
    while i < n - 5:
        b = blob[i]
        if b == 0xE9 or b == 0xE8:
            rel = struct.unpack_from("<i", blob, i + 1)[0]
            out.append((va + i, va + i + 5 + rel))
            i += 5
            continue
        if b == 0x0F and 0x80 <= blob[i + 1] <= 0x8F:
            rel = struct.unpack_from("<i", blob, i + 2)[0]
            out.append((va + i, va + i + 6 + rel))
            i += 6
            continue
        if 0x70 <= b <= 0x7F or b == 0xEB:
            rel = struct.unpack_from("<b", blob, i + 1)[0]
            out.append((va + i, va + i + 2 + rel))
            i += 2
            continue
        i += 1
    return out


def state(path: str) -> dict:
    data = open(path, "rb").read()
    pe = PE(data)
    off = pe.rva_to_off(PATCH_RVA)
    cur = data[off:off + 5] if off is not None else b""
    sha = hashlib.sha256(data).hexdigest()

    st = KNOWN.get(sha)
    known = st is not None
    if st is None:
        # Unknown build: classify by bytes and by the repaired .idata section.
        rebuilt = pe.has_section(".idata")
        if cur == PATCH_NEW:
            st = "rebuilt-legacy-patched" if rebuilt else "released-legacy-patched"
        elif cur == PATCH_ORIG:
            st = "rebuilt" if rebuilt else "released"
        else:
            st = "unknown"

    return {
        "path": path,
        "sha256": sha,
        "state": st,
        "known": known,
        "rebuilt": pe.has_section(".idata"),
        "bytes": cur.hex().upper(),
        "imagebase": pe.imagebase,
        "offset": off,
    }


def _legacy_warning():
    print("[warn] the 5-byte patch is DEPRECATED.")
    print("       The released FAPB 1.6 DLL has a broken import table; the patch")
    print("       only hides the kick crash and does not fix heap corruption.")
    print("       Recommended: python scripts/fapb_rebuild.py --download --install")


def apply_patch(path: str, dry_run: bool = False) -> dict:
    data = bytearray(open(path, "rb").read())
    pe = PE(data)
    off = pe.rva_to_off(PATCH_RVA)
    if off is None:
        raise ValueError("RVA %#x not mapped" % PATCH_RVA)

    cur = bytes(data[off:off + 5])
    st = state(path)

    if st["state"] in ("rebuilt", "rebuilt-legacy-patched"):
        raise ValueError(
            "refusing to patch a rebuilt DLL: the 5-byte patch crashes on bot kick.\n"
            "  current state: %s\n"
            "  rebuilt DLLs must stay unpatched. If it is already patched, run:\n"
            "    python scripts/fapb_patch.py --dll \"%s\" --revert"
            % (st["state"], path))

    if cur == PATCH_NEW:
        return {**st, "changed": False, "state": "already-patched"}

    if cur != PATCH_ORIG:
        raise ValueError(
            "unexpected bytes at RVA %#x: %s (expected %s) - refusing to patch"
            % (PATCH_RVA, cur.hex().upper(), PATCH_ORIG.hex().upper()))

    _legacy_warning()

    # Safety: no other code may branch into the instruction we overwrite.
    hits = [t for (src, t) in branch_targets(bytes(data), pe.text())
            if t == pe.imagebase + PATCH_RVA and src != pe.imagebase + PATCH_RVA]
    if hits:
        raise ValueError("RVA %#x is a branch target (%s) - refusing to patch"
                         % (PATCH_RVA, ", ".join("%#x" % h for h in hits)))

    # Sanity: the jump must land exactly on the loop exit.
    jmp_target = pe.imagebase + PATCH_RVA + 5 + struct.unpack("<i", PATCH_NEW[1:])[0]
    if jmp_target != JUMP_TARGET:
        raise ValueError("computed jump target %#x != %#x" % (jmp_target, JUMP_TARGET))

    if dry_run:
        return {**st, "changed": True, "state": "would-patch", "offset": off}

    data[off:off + 5] = PATCH_NEW
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    out = state(path)
    return {"changed": True, **out, "offset": off}


def revert_patch(path: str) -> dict:
    data = bytearray(open(path, "rb").read())
    pe = PE(data)
    off = pe.rva_to_off(PATCH_RVA)
    cur = bytes(data[off:off + 5])
    if cur == PATCH_ORIG:
        return {**state(path), "changed": False, "state": "already-unpatched"}
    if cur != PATCH_NEW:
        raise ValueError("unexpected bytes at RVA %#x: %s" % (PATCH_RVA, cur.hex().upper()))
    data[off:off + 5] = PATCH_ORIG
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    return {**state(path), "changed": True, "state": "reverted"}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inspect / revert the legacy FAPB 0x1811D 5-byte patch")
    ap.add_argument("--game-dir", default=os.environ.get("FAPB_GAME_DIR", ""),
                    help="CS 1.6 root folder (contains hl.exe)")
    ap.add_argument("--dll", default="", help="explicit path to fapb.dll")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true",
                   help="apply the legacy patch (refused on rebuilt DLLs)")
    g.add_argument("--revert", action="store_true", help="restore original bytes")
    g.add_argument("--dry-run", action="store_true", help="check only")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    try:
        dll = a.dll or find_dll(a.game_dir)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        print("hint: pass --game-dir \"D:\\Games\\Counter-Strike 1.6\"", file=sys.stderr)
        return 2

    try:
        if a.apply or a.dry_run:
            res = apply_patch(dll, dry_run=a.dry_run)
        elif a.revert:
            res = revert_patch(dll)
        else:
            res = state(dll)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 3

    res["dll"] = dll
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("fapb.dll : %s" % dll)
        print("state    : %s   (bytes %s @ RVA %#x)"
              % (res.get("state"), res.get("bytes", ""), PATCH_RVA))
        if "sha256" in res:
            print("sha256   : %s" % res["sha256"])
        st = res.get("state")
        if st == "rebuilt":
            print("           rebuilt DLL, unpatched - this is the recommended state.")
        elif st == "rebuilt-legacy-patched":
            print("           !! rebuilt DLL with the harmful 5-byte patch.")
            print("           -> run --revert (or reinstall the rebuilt DLL)")
        elif st == "released":
            print("           released DLL, unpatched - upstream binary is broken.")
            print("           -> rebuild it: python scripts/fapb_rebuild.py --download --install")
        elif st == "released-legacy-patched":
            print("           released DLL + legacy 5-byte patch.")
            print("           -> works around the kick crash, but rebuilding is safer.")
        elif st == "unknown":
            print("           !! unknown build / unexpected bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
