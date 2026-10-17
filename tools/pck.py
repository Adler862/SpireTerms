"""Minimal Godot 4 PCK reader (read-only).

Only handles the plain (unencrypted) case, which is what we need to pull
localization JSON out of SlayTheSpire2.pck.

PCK v2 header layout (little endian):
    0   char[4]  "GDPC"
    4   u32      pack format version
    8   u32      engine major
    12  u32      engine minor
    16  u32      engine patch
    20  u32      pack flags
    24  u64      file base
    32  u32[16]  reserved
    96  u32      file count
    entries follow

Entry:
    u32   path length
    u8[]  path (utf-8), zero padded so the 4-byte prefix + path stays 4-aligned
    u64   offset (absolute from start of pack)
    u64   size
    u8[16] md5
    u32   flags
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"GDPC"
FLAG_ENCRYPTED = 1 << 0


@dataclass(frozen=True)
class Entry:
    path: str
    offset: int
    size: int
    flags: int


class Pck:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh = open(self.path, "rb")
        self.version, self.file_base, self.entries = self._read_index()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "Pck":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read_index(self) -> tuple[int, int, list[Entry]]:
        fh = self._fh
        header = fh.read(4)
        if header != MAGIC:
            raise ValueError(f"not a pck: magic={header!r}")
        (fmt,) = struct.unpack("<I", fh.read(4))
        fh.read(12)  # engine version
        if fmt >= 3:
            # v3 moves the index to the end of the pack and stores its offset
            # right after file_base.
            fh.read(4)  # pack flags
            (file_base,) = struct.unpack("<Q", fh.read(8))
            (index_offset,) = struct.unpack("<Q", fh.read(8))
            fh.seek(index_offset)
        elif fmt == 2:
            fh.read(4)  # pack flags
            (file_base,) = struct.unpack("<Q", fh.read(8))
            fh.read(64)  # reserved
        else:
            file_base = 0
            fh.read(64)
        (count,) = struct.unpack("<I", fh.read(4))

        entries: list[Entry] = []
        for _ in range(count):
            (path_len,) = struct.unpack("<I", fh.read(4))
            raw = fh.read(path_len)
            pad = (4 - path_len % 4) % 4
            if pad:
                fh.read(pad)
            offset, size = struct.unpack("<QQ", fh.read(16))
            fh.read(16)  # md5
            (flags,) = struct.unpack("<I", fh.read(4))
            # v3 stores the path already padded to 4 bytes, so the decoded
            # string can carry trailing NULs.
            name = raw.decode("utf-8", "replace").rstrip("\x00")
            entries.append(Entry(name, offset, size, flags))
        return fmt, file_base, entries

    def read(self, entry: Entry) -> bytes:
        if entry.flags & FLAG_ENCRYPTED:
            raise ValueError(f"encrypted entry: {entry.path}")
        # Offsets are relative to file_base in every format version we know of.
        self._fh.seek(self.file_base + entry.offset)
        data = self._fh.read(entry.size)
        if len(data) != entry.size:
            raise ValueError(f"short read for {entry.path}")
        return data

    def find(self, suffix: str) -> list[Entry]:
        needle = suffix.replace("\\", "/")
        return [e for e in self.entries if e.path.endswith(needle)]

    def one(self, suffix: str) -> Entry:
        hits = self.find(suffix)
        if len(hits) != 1:
            raise LookupError(f"{suffix!r}: expected 1 match, got {len(hits)}")
        return hits[0]

    def extract(self, entry: Entry, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.read(entry))
        return dest


if __name__ == "__main__":
    import sys

    pck_path = sys.argv[1]
    pattern = sys.argv[2] if len(sys.argv) > 2 else "localization/"
    with Pck(pck_path) as pck:
        print(f"format=v{pck.version} files={len(pck.entries)}")
        for e in pck.entries:
            if pattern in e.path:
                print(f"{e.size:>10}  {e.path}")
