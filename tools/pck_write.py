"""Minimal Godot 4 (pack format v3) PCK writer.

Only what a data-only mod needs: flat file list -> uncompressed pck. Verified
against SlayTheSpire2.pck layout: 0x70 byte header, 16-byte aligned payloads,
index at the end with NUL-padded (4-byte aligned, length included) paths.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

HEADER_SIZE = 0x70
MAGIC = b"GDPC"
FORMAT_VERSION = 3
ENGINE_VERSION = (4, 5, 1)
PACK_FLAGS = 2


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def write_pck(dest: str | Path, files: dict[str, bytes]) -> Path:
    dest = Path(dest)
    buf = bytearray()
    buf += MAGIC
    buf += struct.pack("<I", FORMAT_VERSION)
    buf += struct.pack("<III", *ENGINE_VERSION)
    buf += struct.pack("<I", PACK_FLAGS)
    buf += struct.pack("<Q", HEADER_SIZE)  # file_base
    buf += struct.pack("<Q", 0)  # index_offset, patched later
    buf += b"\x00" * (HEADER_SIZE - len(buf))

    entries: list[tuple[str, int, int, bytes]] = []
    for name in sorted(files):
        data = files[name]
        buf += b"\x00" * ((-len(buf)) % 16)
        offset = len(buf) - HEADER_SIZE  # stored relative to file_base
        buf += data
        entries.append((name, offset, len(data), hashlib.md5(data).digest()))

    index_offset = len(buf)
    buf += struct.pack("<I", len(entries))
    for name, offset, size, digest in entries:
        raw = name.encode("utf-8")
        pad = (4 - len(raw) % 4) % 4
        buf += struct.pack("<I", len(raw) + pad)
        buf += raw + b"\x00" * pad
        buf += struct.pack("<QQ", offset, size)
        buf += digest
        buf += struct.pack("<I", 0)

    struct.pack_into("<Q", buf, 0x20, index_offset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(buf))
    return dest


def files_from_dir(root: str | Path) -> dict[str, bytes]:
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
