#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fapb_rebuild.py - rebuild fapb.dll with a real import table.

Why
---
The FAPB 1.6 release DLL (SHA-256 606E7A6A...3553, 643072 bytes) was
produced by dumping a UPX-packed YaPB 2.55b process.  The dump kept the
unpacked code, but its PE import directory still describes only the UPX
stub.  The 84 kernel32 imports the real code calls live in the dump's
stale IAT at RVA 0x5A000; after LoadLibrary those slots still contain the
addresses they had in the dump process, so the loader never fixes them.
That is why the shipped DLL corrupts the heap / fails with "badf load",
and why patching one instruction is not a real fix.

This script takes the pinned upstream artifacts:

    tools/artifacts/yapb.dll      188416 bytes, packed YaPB 2.55b
    tools/artifacts/yapb_b1.bin   811008 bytes, dump @ 0x10000000
    tools/artifacts/yapb_b2.bin   811008 bytes, dump @ 0x0A630000

and builds a normal PE image:

    * .text   copied from dump b1, with YAPB -> FAPB branding
    * .rsrc   copied from the packed file, same branding
    * .reloc  recovered by diffing b1/b2 (9796 HIGHLOW entries)
    * .idata  one KERNEL32.dll descriptor, INT + 84 hint/name records,
              FirstThunk = 0x5A000 (the IAT the code already uses)

The output is deterministic.  It is verified against the known-good
SHA-256 9AFDAA67...8C96 and refuses to claim success otherwise.

The repaired DLL must stay UNPATCHED: the old 0x1811D 5-byte patch makes
the destructor skip the name-slot release and crashes this build on bot
kick (see docs/fapb-dll-repair.md).

Usage
-----
    # download the pinned artifacts from the FAPB repo into tools/artifacts
    python scripts/fapb_rebuild.py --download

    # build only
    python scripts/fapb_rebuild.py

    # build and install into the game (backup is made automatically)
    python scripts/fapb_rebuild.py --install --game-dir "D:\\CS1.6"

No game files are modified unless --install is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

# --- pinned upstream --------------------------------------------------------
REPO = "Faker1147/FAPB"
COMMIT = "4fae46026d296946c196d4c1bcc25ead3036a9bb"
RAW_URL = "https://raw.githubusercontent.com/%s/%s/tools/artifacts/%%s" % (REPO, COMMIT)

ARTIFACTS = {
    "yapb.dll": {
        "sha256": "00dfb600184f4819623701a0450fec39cff73cae270862a7fb52c51ef93080c2",
        "size": 188416,
    },
    "yapb_b1.bin": {
        "sha256": "3a49067e79715464e38faea3bdefe835162ad925e51b5d9b3dd66fd556e5f075",
        "size": 811008,
    },
    "yapb_b2.bin": {
        "sha256": "247da26c8812bbc5d52dc01070bea96ea6a64ec23ea3ff7955f3c66cddac65bc",
        "size": 811008,
    },
    "yapb_b1.bin.txt": {"sha256": None, "size": 25},
    "yapb_b2.bin.txt": {"sha256": None, "size": 25},
}

# --- original image layout --------------------------------------------------
IMAGE_BASE = 0x10000000
IMAGE_SIZE = 0xC6000
TEXT_RVA = 0x1000
TEXT_SIZE = 0x96000
RSRC_RVA = 0xC4000
RSRC_SIZE = 0x1A00
RSRC_FILE_OFFSET = 0x2C600
RELOC_RVA = 0xC6000
IAT_RVA = 0x5A000
NAMES_RVA = 0xBF008
NAMES_END = 0xBF581          # first byte after the last name's NUL
IMPORT_COUNT = 84
IDATA_RVA = 0xCC000

BASE_B1 = 0x10000000
BASE_B2 = 0x0A630000
ENTRY_RVA = 0x4437B

# --- known-good output ------------------------------------------------------
GOOD_SHA256 = "9afdaa6796e59026bdd65425a29ab46429aee11d9fee1205ff05351b2dd08c96"
GOOD_SIZE = 645120

GAME_DLL_REL = os.path.join("cstrike", "addons", "fapb", "dlls", "fapb.dll")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_artifacts_dir() -> Path:
    return repo_root() / "tools" / "artifacts"


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
def verify_inputs(art: Path) -> dict:
    info = {}
    for name, meta in ARTIFACTS.items():
        p = art / name
        if not p.is_file():
            raise SystemExit(
                "missing artifact: %s\n"
                "  put the pinned files in %s or run with --download" % (p, art))
        data = p.read_bytes()
        info[name] = {"path": str(p), "size": len(data)}
        if meta.get("size") is not None and len(data) != meta["size"]:
            raise SystemExit("artifact %s has size %d, expected %d"
                             % (name, len(data), meta["size"]))
        want = meta.get("sha256")
        if want:
            got = sha256_bytes(data)
            info[name]["sha256"] = got
            if got != want:
                raise SystemExit("artifact %s has sha256 %s, expected %s"
                                 % (name, got, want))
    return info


def download_artifacts(art: Path) -> None:
    art.mkdir(parents=True, exist_ok=True)
    for name, meta in ARTIFACTS.items():
        dst = art / name
        if dst.is_file():
            data = dst.read_bytes()
            if meta.get("size") is None or len(data) == meta["size"]:
                if not meta.get("sha256") or sha256_bytes(data) == meta["sha256"]:
                    print("cached : %s" % dst)
                    continue
        url = RAW_URL % name
        print("fetch  : %s" % url)
        req = urllib.request.Request(url, headers={"User-Agent": "fapb-kickfix/1.2.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except Exception as e:
            raise SystemExit("download failed for %s: %s\n"
                             "  Download it manually from the URL above and put it in %s"
                             % (name, e, art))
        if meta.get("size") is not None and len(data) != meta["size"]:
            raise SystemExit("downloaded %s has size %d, expected %d"
                             % (name, len(data), meta["size"]))
        if meta.get("sha256") and sha256_bytes(data) != meta["sha256"]:
            raise SystemExit("downloaded %s has an unexpected sha256" % name)
        dst.write_bytes(data)
        print("saved  : %s (%d bytes, %s)" % (dst, len(data), sha256_bytes(data)))


def read_meta(path: Path, default_base: int) -> int:
    txt = Path(str(path) + ".txt")
    if not txt.is_file():
        return default_base
    try:
        base = int(txt.read_text(encoding="ascii").strip().split("|")[0])
    except (ValueError, IndexError):
        raise SystemExit("bad sidecar: %s" % txt)
    if base != default_base:
        raise SystemExit("sidecar %s says base %#x, expected %#x"
                         % (txt, base, default_base))
    return base


def parse_names(b1: bytes) -> list:
    names = []
    i = NAMES_RVA
    while i < NAMES_END and b1[i] == 1:
        j = b1.find(b"\x00", i + 1, i + 200)
        if j < 0:
            raise SystemExit("unterminated import name at %#x" % i)
        names.append((i, b1[i + 1:j].decode("latin1")))
        i = j + 1
    if len(names) != IMPORT_COUNT:
        raise SystemExit("expected %d import names, parsed %d"
                         % (IMPORT_COUNT, len(names)))
    return names


def recover_relocations(b1: bytes, b2: bytes, base1: int, base2: int):
    delta = (base2 - base1) & 0xFFFFFFFF
    out = []
    for off in range(TEXT_RVA, TEXT_RVA + TEXT_SIZE - 3):
        v1 = struct.unpack_from("<I", b1, off)[0]
        if not (base1 <= v1 < base1 + IMAGE_SIZE):
            continue
        v2 = struct.unpack_from("<I", b2, off)[0]
        if ((v2 - v1) & 0xFFFFFFFF) == delta:
            out.append(off)
    return out


def make_reloc_section(relocs) -> bytes:
    pages = defaultdict(list)
    for rva in relocs:
        pages[rva & 0xFFFFF000].append(rva & 0xFFF)
    out = bytearray()
    for page in sorted(pages):
        entries = sorted(set(pages[page]))
        for i in range(0, len(entries), 0x3F0):
            chunk = entries[i:i + 0x3F0]
            size = 8 + 2 * len(chunk)
            pad = 2 if size % 4 else 0
            if pad:
                size += 2
            out += struct.pack("<II", page, size)
            out += b"".join(struct.pack("<H", e | 0x3000) for e in chunk)
            if pad:
                out += b"\x00\x00"
    return bytes(out)


def patch_branding(text: bytearray, rsrc: bytearray) -> None:
    replacements = [
        (b"YAPB", b"FAPB"), (b"YaPB", b"FAPB"), (b"Yapb", b"Fapb"), (b"yapb", b"fapb"),
        (b"yb_", b"fb_"), (b"\x00yb\x00", b"\x00fb\x00"), (b"|yb|", b"|fb|"),
    ]
    for buf in (text, rsrc):
        for old, new in replacements:
            buf[:] = bytes(buf).replace(old, new)
        for old, new in (("YAPB", "FAPB"), ("YaPB", "FAPB"),
                         ("Yapb", "Fapb"), ("yapb", "fapb")):
            buf[:] = bytes(buf).replace(old.encode("utf-16le"), new.encode("utf-16le"))
        # Keep the original authors' credit even after the rename.
        buf[:] = bytes(buf).replace(b"FAPB Development Team", b"YaPB Development Team")
        buf[:] = bytes(buf).replace(b"FAPB Dev Team", b"YaPB Dev Team")


def make_idata(names) -> bytes:
    """Layout: descriptors, INT, DLL name, hint/name records.

    The dump stores its 84 names as ``01 <name> 00`` (one flag byte, no
    real IMAGE_IMPORT_BY_NAME hint word).  A real import table needs
    ``<WORD hint=0> <name> 00``, so build fresh records.
    """
    ndesc = 40                       # one real + one null descriptor
    int_bytes = (IMPORT_COUNT + 1) * 4
    dll_name = b"KERNEL32.dll\x00"
    hint_rva = IDATA_RVA + ndesc + int_bytes + len(dll_name)

    records = []
    offsets = []
    offset = 0
    for _, name in names:
        rec = b"\x00\x00" + name.encode("ascii") + b"\x00"
        if len(rec) & 1:
            rec += b"\x00"
        offsets.append(offset)
        records.append(rec)
        offset += len(rec)

    int_rvas = [hint_rva + off for off in offsets]

    blob = bytearray()
    blob += struct.pack("<IIIII", IDATA_RVA + ndesc, 0, 0,
                        IDATA_RVA + ndesc + int_bytes, IAT_RVA)
    blob += b"\x00" * 20
    blob += b"".join(struct.pack("<I", v) for v in int_rvas) + b"\x00\x00\x00\x00"
    blob += dll_name
    blob += b"".join(records)
    return bytes(blob)


def build_headers(packed: bytes, reloc: bytes, idata_size: int) -> bytearray:
    out = bytearray(packed[:0x400])
    pe = 0x100
    opt = pe + 24

    idata_raw_size = align(idata_size, 0x200)
    size_of_image = align(IDATA_RVA + idata_size, 0x1000)

    struct.pack_into("<H", out, pe + 6, 5)              # NumberOfSections
    struct.pack_into("<I", out, opt + 16, ENTRY_RVA)    # AddressOfEntryPoint
    struct.pack_into("<I", out, opt + 56, size_of_image)
    struct.pack_into("<I", out, opt + 60, 0x400)        # SizeOfHeaders
    struct.pack_into("<I", out, opt + 64, 0)            # CheckSum
    struct.pack_into("<I", out, opt + 4, TEXT_SIZE)     # SizeOfCode
    struct.pack_into("<I", out, opt + 8,
                     RSRC_SIZE + align(len(reloc), 0x200) + idata_raw_size)
    struct.pack_into("<I", out, opt + 12, 0x2D000)      # SizeOfUninitializedData
    struct.pack_into("<I", out, opt + 20, TEXT_RVA)     # BaseOfCode
    struct.pack_into("<I", out, opt + 24, 0x97000)      # BaseOfData

    struct.pack_into("<II", out, opt + 96 + 10 * 8, 0, 0)         # LoadConfig
    struct.pack_into("<II", out, opt + 96 + 1 * 8, IDATA_RVA, 40)  # Import
    struct.pack_into("<II", out, opt + 96 + 5 * 8, RELOC_RVA, len(reloc))

    sec = opt + struct.unpack_from("<H", out, pe + 20)[0]

    def section(name, vsize, va, rawsize, rawptr, chars):
        return struct.pack("<8sIIIIIIHHI", name.encode().ljust(8, b"\0"),
                           vsize, va, rawsize, rawptr, 0, 0, 0, 0, chars)

    out[sec:sec + 40] = section(".text", TEXT_SIZE, TEXT_RVA, TEXT_SIZE, 0x400, 0xE0000080)
    out[sec + 40:sec + 80] = section(".data", 0x2D000, 0x97000, 0, 0, 0xC0000040)
    out[sec + 80:sec + 120] = section(".rsrc", 0x2000, RSRC_RVA, RSRC_SIZE,
                                      0x400 + TEXT_SIZE, 0x40000040)
    reloc_raw = align(0x400 + TEXT_SIZE + RSRC_SIZE, 0x200)
    out[sec + 120:sec + 160] = section(".reloc", len(reloc), RELOC_RVA,
                                      align(len(reloc), 0x200), reloc_raw, 0x42000040)
    idata_raw = reloc_raw + align(len(reloc), 0x200)
    out[sec + 160:sec + 200] = section(".idata", idata_size, IDATA_RVA,
                                      idata_raw_size, idata_raw, 0xC0000040)
    return out


def build_image(art: Path) -> tuple:
    packed = (art / "yapb.dll").read_bytes()
    b1 = (art / "yapb_b1.bin").read_bytes()
    b2 = (art / "yapb_b2.bin").read_bytes()
    base1 = read_meta(art / "yapb_b1.bin", BASE_B1)
    base2 = read_meta(art / "yapb_b2.bin", BASE_B2)

    names = parse_names(b1)
    relocs = recover_relocations(b1, b2, base1, base2)
    reloc = make_reloc_section(relocs)

    text = bytearray(b1[TEXT_RVA:TEXT_RVA + TEXT_SIZE])
    rsrc = bytearray(packed[RSRC_FILE_OFFSET:RSRC_FILE_OFFSET + RSRC_SIZE])
    patch_branding(text, rsrc)

    idata = make_idata(names)
    buf = build_headers(packed, reloc, len(idata))
    if len(buf) != 0x400:
        raise SystemExit("internal error: header size %#x" % len(buf))
    buf += text
    buf += rsrc
    reloc_raw = align(0x400 + TEXT_SIZE + RSRC_SIZE, 0x200)
    if len(buf) != reloc_raw:
        raise SystemExit("internal error: rsrc layout %#x != %#x"
                         % (len(buf), reloc_raw))
    buf += reloc
    buf += b"\0" * (align(len(buf), 0x200) - len(buf))
    buf += idata
    buf += b"\0" * (align(len(buf), 0x200) - len(buf))

    meta = {
        "imports": len(names),
        "first_import": names[0][1],
        "last_import": names[-1][1],
        "relocations": len(relocs),
        "idata_size": len(idata),
    }
    return bytes(buf), meta


def inspect_image(data: bytes) -> dict:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    sections = []
    sec = opt + optsz
    for i in range(nsec):
        o = sec + i * 40
        name = data[o:o + 8].rstrip(b"\0").decode("latin-1", "replace")
        vs, va, rs, ra = struct.unpack_from("<IIII", data, o + 8)
        sections.append({"name": name, "rva": va, "vsize": vs,
                         "raw": ra, "rawsize": rs})
    return {
        "sections": sections,
        "entry": struct.unpack_from("<I", data, opt + 16)[0],
        "imagebase": struct.unpack_from("<I", data, opt + 28)[0],
        "sizeofimage": struct.unpack_from("<I", data, opt + 56)[0],
    }


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------
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
        if not c:
            continue
        if os.path.isfile(os.path.join(c, "hl.exe")):
            return os.path.abspath(c)
        if os.path.isdir(c):
            try:
                for name in sorted(os.listdir(c)):
                    sub = os.path.join(c, name)
                    if os.path.isfile(os.path.join(sub, "hl.exe")):
                        return os.path.abspath(sub)
            except OSError:
                pass
    return ""


def install_image(data: bytes, game_dir: str) -> str:
    game = detect_game_dir(game_dir)
    if not game:
        raise SystemExit("cannot locate CS 1.6 (hl.exe); pass --game-dir")
    dst = os.path.join(game, GAME_DLL_REL)
    if not os.path.isfile(dst):
        raise SystemExit("fapb.dll not installed at %s" % dst)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(game, "cstrike", "addons", "fapb",
                              "backup", "rebuild-" + stamp)
    os.makedirs(backup_dir, exist_ok=True)
    shutil.copy2(dst, os.path.join(backup_dir, "fapb.dll"))

    tmp = dst + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        shutil.copystat(dst, tmp)
        os.replace(tmp, dst)
    except PermissionError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SystemExit("cannot replace %s - close the game first" % dst)
    return backup_dir


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rebuild fapb.dll with a real KERNEL32 import table")
    ap.add_argument("--artifacts", default="",
                    help="folder with yapb.dll / yapb_b1.bin / yapb_b2.bin "
                         "(default: tools/artifacts)")
    ap.add_argument("--download", action="store_true",
                    help="download the pinned artifacts from %s@%s" % (REPO, COMMIT[:12]))
    ap.add_argument("--out", default="",
                    help="output path (default: dist/fapb.dll)")
    ap.add_argument("--install", action="store_true",
                    help="replace cstrike/addons/fapb/dlls/fapb.dll (backup first)")
    ap.add_argument("--game-dir", default="", help="CS 1.6 root folder")
    ap.add_argument("--force", action="store_true",
                    help="write output even if it does not match the known-good hash")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    a = ap.parse_args(argv)

    art = Path(a.artifacts).resolve() if a.artifacts else default_artifacts_dir()
    if a.download:
        download_artifacts(art)
    verify_inputs(art)

    data, meta = build_image(art)
    sha = sha256_bytes(data)
    meta.update({"sha256": sha, "size": len(data),
                 "known_good": sha == GOOD_SHA256 and len(data) == GOOD_SIZE})

    out = Path(a.out).resolve() if a.out else repo_root() / "dist" / "fapb.dll"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    backup = None
    if a.install:
        backup = install_image(data, a.game_dir)

    meta["path"] = str(out)
    if backup:
        meta["backup"] = backup
    if a.json:
        print(json.dumps(meta, indent=2, ensure_ascii=False))
    else:
        print("artifacts : %s" % art)
        print("imports   : %d (%s .. %s)" % (meta["imports"],
                                             meta["first_import"], meta["last_import"]))
        print("relocs    : %d" % meta["relocations"])
        print("output    : %s (%d bytes)" % (out, len(data)))
        print("sha256    : %s" % sha)
        print("verified  : %s" % ("YES (known-good build)" if meta["known_good"]
                                  else "NO - unexpected hash"))
        if backup:
            print("installed : %s" % os.path.join(
                detect_game_dir(a.game_dir), GAME_DLL_REL))
            print("backup    : %s" % backup)

    if not meta["known_good"]:
        print("error: output does not match the verified rebuild (%s)"
              % GOOD_SHA256, file=sys.stderr)
        return 4 if not a.force else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
