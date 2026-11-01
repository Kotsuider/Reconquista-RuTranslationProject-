#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Majiro engine resource archive (.arc) reader/writer.

Python re-implementation of GARbro's ``ArcFormats/Majiro/ArcMajiro.cs``
(original C# code by morkt, MIT licence) with read *and* write support for
all three known index versions.

Binary layout
-------------
::

    0x00  char[10]  "MajiroArcV"
    0x0A  char       version digit, '1' | '2' | '3'
    0x0B  char[5]   ".000\\0"
    0x10  uint32     entry count
    0x14  uint32     offset of the name table
    0x18  uint32     offset of the first file (data section)
    0x1C  entry[]    index, sorted by name hash (ascending)

Index entry
    v1:  uint32 hash | uint32 offset                       (size = next offset - offset)
    v2:  uint32 hash | uint32 offset | uint32 size
    v3:  uint64 hash | uint32 offset | uint32 size

``hash`` is the standard CRC-32 of the file name encoded in cp932.
v1 archives carry one extra sentinel entry (hash 0, offset = end of data)
right after the last real entry; it exists purely to give the last file its
size.  Names are stored back-to-back as NUL-terminated cp932 strings in the
very same order as the index.

Usage
-----
    python majiro_arc.py list     game.arc
    python majiro_arc.py info     game.arc
    python majiro_arc.py count    game.arc
    python majiro_arc.py unpack   game.arc out_dir
    python majiro_arc.py pack     out_dir  new.arc --version 1
    python majiro_arc.py repack   game.arc patch_dir modded.arc
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence

__all__ = [
    "MajiroError",
    "FormatError",
    "Entry",
    "Archive",
    "pack_archive",
    "crc32_name",
    "DEFAULT_ENCODING",
]

SIGNATURE = b"MajiroArcV"
SIGNATURE_TAIL = b".000\x00"
HEADER_SIZE = 0x1C
SUPPORTED_VERSIONS = (1, 2, 3)
DEFAULT_ENCODING = "cp932"
MAX_ENTRIES = 0x100000
COPY_CHUNK = 1 << 20


class MajiroError(Exception):
    """Base class for every error raised by this module."""


class FormatError(MajiroError):
    """Archive structure is invalid or unsupported."""


class EntryCollisionError(MajiroError):
    """Two different names produced the same hash / archive name."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def crc32_name(name: bytes) -> int:
    """CRC-32 of a cp932-encoded file name (the Majiro index hash)."""
    return zlib.crc32(name) & 0xFFFFFFFF


def entry_size(version: int) -> int:
    """Size of one index record for the given archive version."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported Majiro archive version: {version}")
    return 4 * (version + 1)


def hash_size(version: int) -> int:
    return 8 if version == 3 else 4


def encode_name(name: str, encoding: str = DEFAULT_ENCODING) -> bytes:
    try:
        return name.encode(encoding, "surrogateescape")
    except UnicodeEncodeError as exc:  # pragma: no cover - defensive
        raise MajiroError(f"cannot encode name {name!r} as {encoding}: {exc}") from exc


def decode_name(raw: bytes, encoding: str = DEFAULT_ENCODING) -> str:
    return raw.decode(encoding, "surrogateescape")


def _u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def _u64(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", buf, offset)[0]


def _pad(offset: int, align: int) -> int:
    if align <= 1:
        return offset
    rem = offset % align
    return offset if rem == 0 else offset + (align - rem)


# --------------------------------------------------------------------------
# index entry
# --------------------------------------------------------------------------


@dataclass
class Entry:
    """One file inside a Majiro archive."""

    name: str
    hash: int
    offset: int
    size: int
    index: int = 0
    name_bytes: bytes = b""

    @property
    def hash32(self) -> int:
        """Low 32 bits of the stored hash (v3 keeps 64 bits)."""
        return self.hash & 0xFFFFFFFF

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.name} (offset=0x{self.offset:X}, size={self.size})"


# --------------------------------------------------------------------------
# archive reader
# --------------------------------------------------------------------------


@dataclass
class Archive:
    """Parsed Majiro archive index."""

    path: Path
    version: int
    entries: list[Entry]
    names_offset: int
    data_offset: int
    file_size: int
    names_size: int = 0
    warnings: list[str] = field(default_factory=list)
    encoding: str = DEFAULT_ENCODING

    # -- construction ------------------------------------------------------

    @classmethod
    def open(cls, path: os.PathLike | str, encoding: str = DEFAULT_ENCODING) -> "Archive":
        path = Path(path)
        with path.open("rb") as fh:
            header = fh.read(HEADER_SIZE)
            if len(header) < HEADER_SIZE:
                raise FormatError(f"{path}: file is too small to be a Majiro archive")

            version = cls._parse_header(header, path)
            count, names_offset, data_offset = struct.unpack_from("<III", header, 0x10)

            if count > MAX_ENTRIES:
                raise FormatError(f"{path}: implausible entry count {count}")
            if data_offset < names_offset:
                raise FormatError(
                    f"{path}: name table offset 0x{names_offset:X} is past data offset 0x{data_offset:X}"
                )

            file_size = path.stat().st_size
            if data_offset > file_size:
                raise FormatError(
                    f"{path}: data offset 0x{data_offset:X} is beyond end of file (0x{file_size:X})"
                )

            table_len = (count + (1 if version == 1 else 0)) * entry_size(version)
            table_end = HEADER_SIZE + table_len
            # read everything from the header up to the data section in one go
            blob = fh.read(data_offset - HEADER_SIZE)
            if len(blob) < data_offset - HEADER_SIZE:
                raise FormatError(f"{path}: truncated index")

        warnings: list[str] = []
        if table_end > names_offset:
            raise FormatError(
                f"{path}: index of {count} entries ends at 0x{table_end:X}, "
                f"past the name table at 0x{names_offset:X}"
            )
        if table_end < names_offset:
            warnings.append(
                f"index ends at 0x{table_end:X} but name table starts at 0x{names_offset:X} "
                f"({names_offset - table_end} padding bytes)"
            )

        base = 0  # ``blob`` starts right after the 0x1C-byte header
        names_raw = blob[names_offset - HEADER_SIZE : data_offset - HEADER_SIZE]

        # --- hashes / offsets / sizes ------------------------------------
        raw_records: list[tuple[int, int, int | None]] = []
        for i in range(count):
            pos = base + i * entry_size(version)
            h = _u64(blob, pos) if version == 3 else _u32(blob, pos)
            hs = hash_size(version)
            off = _u32(blob, pos + hs)
            size = None if version == 1 else _u32(blob, pos + hs + 4)
            raw_records.append((h, off, size))

        if version == 1:
            # last size comes from the sentinel record that follows the index
            sentinel_pos = base + count * entry_size(1) + hash_size(1)
            sentinel_off = _u32(blob, sentinel_pos) if sentinel_pos + 4 <= len(blob) else file_size
            ends = [r[1] for r in raw_records[1:]] + [sentinel_off]
            resolved: list[tuple[int, int, int]] = []
            for (h, off, _), nxt in zip(raw_records, ends):
                size = nxt - off if nxt >= off else 0
                resolved.append((h, off, size))
        else:
            resolved = [(h, off, size or 0) for h, off, size in raw_records]

        # --- names --------------------------------------------------------
        names = names_raw.split(b"\x00")
        if names and names[-1] == b"":
            names.pop()
        if len(names) < count:
            raise FormatError(
                f"{path}: name table holds {len(names)} names, index expects {count}"
            )
        if len(names) > count:
            warnings.append(f"name table holds {len(names)} names for {count} entries")

        entries: list[Entry] = []
        for i, (h, off, size) in enumerate(resolved):
            raw = names[i]
            entries.append(
                Entry(
                    name=decode_name(raw, encoding),
                    hash=h,
                    offset=off,
                    size=size,
                    index=i,
                    name_bytes=raw,
                )
            )

        arc = cls(
            path=path,
            version=version,
            entries=entries,
            names_offset=names_offset,
            data_offset=data_offset,
            file_size=file_size,
            names_size=len(names_raw),
            warnings=warnings,
            encoding=encoding,
        )
        arc._validate()
        return arc

    @staticmethod
    def _parse_header(header: bytes, path: Path) -> int:
        if header[:10] != SIGNATURE:
            raise FormatError(f"{path}: not a Majiro archive (bad signature)")
        digit = header[0x0A]
        if not 0x31 <= digit <= 0x33:
            raise FormatError(f"{path}: unsupported archive version byte 0x{digit:02X}")
        if header[0x0B:0x10] != SIGNATURE_TAIL:
            raise FormatError(f"{path}: unexpected header tail {header[0x0B:0x10]!r}")
        return digit - 0x30

    def _validate(self) -> None:
        for e in self.entries:
            if e.offset < self.data_offset:
                raise FormatError(
                    f"entry #{e.index} '{e.name}' starts at 0x{e.offset:X}, "
                    f"before the data section (0x{self.data_offset:X})"
                )
            if e.offset + e.size > self.file_size:
                raise FormatError(
                    f"entry #{e.index} '{e.name}' ends at 0x{e.offset + e.size:X}, "
                    f"beyond end of file (0x{self.file_size:X})"
                )

    # -- data access -------------------------------------------------------

    def read(self, entry: Entry) -> bytes:
        with self.path.open("rb") as fh:
            fh.seek(entry.offset)
            data = fh.read(entry.size)
        if len(data) != entry.size:
            raise FormatError(f"{self.path}: short read for '{entry.name}'")
        return data

    def iter_data(self, fh: BinaryIO | None = None) -> Iterator[tuple[Entry, bytes]]:
        close = False
        if fh is None:
            fh = self.path.open("rb")
            close = True
        try:
            for e in self.entries:
                fh.seek(e.offset)
                data = fh.read(e.size)
                if len(data) != e.size:
                    raise FormatError(f"{self.path}: short read for '{e.name}'")
                yield e, data
        finally:
            if close:
                fh.close()

    # -- extraction --------------------------------------------------------

    def extract(
        self,
        out_dir: os.PathLike | str,
        *,
        flat: bool = False,
        overwrite: bool = False,
        progress=None,
    ) -> int:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        with self.path.open("rb") as fh:
            for entry, data in self.iter_data(fh):
                target = out_dir / safe_relative_path(entry.name, flat=flat)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and not overwrite:
                    raise MajiroError(f"{target} already exists (use --overwrite)")
                target.write_bytes(data)
                written += 1
                if progress is not None:
                    progress(entry, target)
        return written

    # -- reporting ---------------------------------------------------------

    def hash_report(self) -> tuple[int, int]:
        """(matching, total) — how many stored hashes equal crc32(name)."""
        matching = sum(1 for e in self.entries if crc32_name(e.name_bytes) == e.hash32)
        return matching, len(self.entries)

    def to_dict(self) -> dict:
        matching, total = self.hash_report()
        return {
            "path": str(self.path),
            "version": self.version,
            "entries": total,
            "names_offset": self.names_offset,
            "data_offset": self.data_offset,
            "file_size": self.file_size,
            "names_size": self.names_size,
            "hash_matches": matching,
            "warnings": list(self.warnings),
            "files": [
                {
                    "index": e.index,
                    "name": e.name,
                    "hash": e.hash,
                    "hash32": e.hash32,
                    "offset": e.offset,
                    "size": e.size,
                }
                for e in self.entries
            ],
        }


def safe_relative_path(name: str, *, flat: bool = False) -> Path:
    """Turn an archive name into a path that cannot escape the output dir."""
    normalized = name.replace("\\", "/").strip("/")
    if flat:
        normalized = normalized.rsplit("/", 1)[-1]
    parts = []
    for part in normalized.split("/"):
        if part in ("", ".", ".."):
            continue
        if len(part) >= 2 and part[1] == ":":  # "C:foo"
            part = part[2:]
        if not part:
            continue
        parts.append(part)
    if not parts:
        raise MajiroError(f"cannot derive a safe output path from {name!r}")
    return Path(*parts)


# --------------------------------------------------------------------------
# archive writer
# --------------------------------------------------------------------------


@dataclass
class PackItem:
    """A file to be stored in the archive."""

    name: str
    data: bytes | None = None
    source: Path | None = None

    def size(self) -> int:
        if self.data is not None:
            return len(self.data)
        if self.source is None:
            raise MajiroError(f"item {self.name!r} has neither data nor source")
        return self.source.stat().st_size

    def write_to(self, fh: BinaryIO) -> int:
        if self.data is not None:
            fh.write(self.data)
            return len(self.data)
        if self.source is None:
            raise MajiroError(f"item {self.name!r} has neither data nor source")
        total = 0
        with self.source.open("rb") as src:
            while True:
                chunk = src.read(COPY_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
        return total


def pack_archive(
    items: Sequence[PackItem],
    dest: os.PathLike | str,
    *,
    version: int = 1,
    align: int = 1,
    encoding: str = DEFAULT_ENCODING,
    strict: bool = False,
) -> Path:
    """Write ``items`` into a Majiro archive at ``dest``.

    ``align`` pads the data section start (and each file, when > 1) to a
    multiple of the given value; 1 means "no padding", which is what the
    engine itself produces.  ``strict`` turns hash collisions into errors.
    """
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported Majiro archive version: {version}")
    if version == 1 and align > 1:
        # v1 stores no sizes — they are derived from the next offset, so any
        # padding between files would be read back as file content.
        raise ValueError("version 1 archives cannot be aligned (no per-file sizes)")
    dest = Path(dest)

    prepared: list[tuple[bytes, str, int, PackItem]] = []
    for item in items:
        raw = encode_name(item.name, encoding)
        prepared.append((raw, item.name, crc32_name(raw), item))

    if strict:
        seen: dict[int, str] = {}
        for raw, name, h, _ in prepared:
            if h in seen:
                raise EntryCollisionError(
                    f"hash collision 0x{h:08X}: {seen[h]!r} vs {name!r}"
                )
            seen[h] = name

    # the engine binary-searches the index, so it must be hash-sorted
    prepared.sort(key=lambda t: t[2])

    count = len(prepared)
    esize = entry_size(version)
    table_len = (count + (1 if version == 1 else 0)) * esize
    names_offset = HEADER_SIZE + table_len
    names_blob = b"".join(raw + b"\x00" for raw, _, _, _ in prepared)
    data_offset = _pad(names_offset + len(names_blob), align)

    offsets: list[int] = []
    cursor = data_offset
    for _, _, _, item in prepared:
        cursor = _pad(cursor, align) if align > 1 else cursor
        offsets.append(cursor)
        cursor += item.size()
    end_offset = cursor

    if end_offset > 0xFFFFFFFF:
        raise MajiroError("archive would exceed 4 GiB, which the format cannot address")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        fh.write(SIGNATURE)
        fh.write(b"%d" % version)
        fh.write(SIGNATURE_TAIL)
        fh.write(struct.pack("<III", count, names_offset, data_offset))
        fh.write(b"\x00" * table_len)  # index placeholder
        fh.write(names_blob)
        fh.write(b"\x00" * (data_offset - names_offset - len(names_blob)))

        written_sizes: list[int] = []
        for (_, _, _, item), off in zip(prepared, offsets):
            fh.write(b"\x00" * (off - fh.tell()))
            written_sizes.append(item.write_to(fh))
        if fh.tell() != end_offset:
            fh.write(b"\x00" * (end_offset - fh.tell()))

        # --- index --------------------------------------------------------
        fh.seek(HEADER_SIZE)
        for (_, _, h, _), off, size in zip(prepared, offsets, written_sizes):
            if version == 3:
                fh.write(struct.pack("<QII", h, off, size))
            elif version == 2:
                fh.write(struct.pack("<III", h, off, size))
            else:
                fh.write(struct.pack("<II", h, off))
        if version == 1:
            fh.write(struct.pack("<II", 0, end_offset))

    return dest


def items_from_directory(
    src: os.PathLike | str,
    *,
    recursive: bool = True,
    keep_dirs: bool = False,
) -> list[PackItem]:
    """Collect files from ``src`` as pack items.

    Majiro archives are flat, so directory names are dropped by default;
    pass ``keep_dirs`` to store relative paths with backslashes.
    """
    src = Path(src)
    if not src.is_dir():
        raise MajiroError(f"{src} is not a directory")
    pattern = "**/*" if recursive else "*"
    items: list[PackItem] = []
    for path in sorted(src.glob(pattern)):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if keep_dirs:
            name = str(rel).replace("/", "\\")
        else:
            name = rel.name
        items.append(PackItem(name=name, source=path))
    return items


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _human(size: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size} B"


def _cmd_list(args) -> int:
    arc = Archive.open(args.archive, encoding=args.encoding)
    if args.json:
        print(json.dumps(arc.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"{arc.path.name}: MajiroArcV{arc.version}.000, {len(arc.entries)} file(s)")
    for e in arc.entries:
        print(f"  0x{e.hash:08X}  {e.size:>10}  0x{e.offset:08X}  {e.name}")
    return 0


def _cmd_info(args) -> int:
    arc = Archive.open(args.archive, encoding=args.encoding)
    matching, total = arc.hash_report()
    esize = entry_size(arc.version)
    table_end = HEADER_SIZE + (len(arc.entries) + (1 if arc.version == 1 else 0)) * esize

    if args.json:
        data = arc.to_dict()
        data["table_end"] = table_end
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"file            : {arc.path}")
    print(f"version         : MajiroArcV{arc.version}.000")
    print(f"entries         : {len(arc.entries)}")
    print(f"index range     : 0x{HEADER_SIZE:X}..0x{table_end:X} ({esize} B/entry)")
    print(f"name table      : 0x{arc.names_offset:X}..0x{arc.data_offset:X} "
          f"({arc.names_size} B)")
    print(f"data section    : 0x{arc.data_offset:X}..0x{arc.file_size:X} "
          f"({_human(arc.file_size - arc.data_offset)})")
    print(f"archive size    : {_human(arc.file_size)}")
    print(f"crc32 names ok  : {matching}/{total}")
    for w in arc.warnings:
        print(f"warning         : {w}")

    # continuity of the data section — useful when hunting for a broken index
    gaps = 0
    overlaps = 0
    ordered = sorted(arc.entries, key=lambda e: e.offset)
    cursor = arc.data_offset
    for e in ordered:
        if e.offset > cursor:
            gaps += 1
        elif e.offset < cursor:
            overlaps += 1
        cursor = max(cursor, e.offset + e.size)
    print(f"gaps / overlaps : {gaps} / {overlaps}")
    if cursor != arc.file_size:
        print(f"note            : data ends at 0x{cursor:X}, file ends at 0x{arc.file_size:X}")
    return 0


def _cmd_unpack(args) -> int:
    arc = Archive.open(args.archive, encoding=args.encoding)
    if not args.quiet:
        print(f"{arc.path.name}: {len(arc.entries)} file(s), MajiroArcV{arc.version}.000")

    def progress(entry: Entry, target: Path) -> None:
        if not args.quiet:
            print(f"  {entry.name} -> {target}")

    written = arc.extract(args.outdir, flat=args.flat, overwrite=args.overwrite,
                          progress=progress)
    if not args.quiet:
        print(f"extracted {written} file(s) to {args.outdir}")
    return 0


def _cmd_pack(args) -> int:
    if args.base:
        items = _items_from_base(args.base, args.srcdir, args)
        version = args.version
        if version is None:
            version = Archive.open(args.base, encoding=args.encoding).version
    else:
        items = items_from_directory(args.srcdir, recursive=not args.no_recursive,
                                     keep_dirs=args.keep_dirs)
        if args.exclude:
            import fnmatch

            items = [i for i in items
                     if not any(fnmatch.fnmatch(i.name, pat) for pat in args.exclude)]
        version = args.version if args.version is not None else 1
    if not items:
        raise MajiroError(f"nothing to pack in {args.srcdir}")

    dest = pack_archive(items, args.archive, version=version, align=args.align,
                        encoding=args.encoding, strict=args.strict)
    if not args.quiet:
        total = dest.stat().st_size
        print(f"packed {len(items)} file(s) into {dest} "
              f"(MajiroArcV{version}.000, {_human(total)})")
    return 0


def _items_from_base(base: os.PathLike | str, patch_dir: os.PathLike | str, args) -> list[PackItem]:
    """Keep the original index order, swapping in files from ``patch_dir``."""
    arc = Archive.open(base, encoding=args.encoding)
    patch_root = Path(patch_dir)
    used: set[str] = set()
    items: list[PackItem] = []
    for e in arc.entries:
        candidate = patch_root / safe_relative_path(e.name)
        if candidate.is_file():
            items.append(PackItem(name=e.name, source=candidate))
            used.add(candidate.resolve().as_posix())
        else:
            items.append(PackItem(name=e.name, data=arc.read(e)))
    if patch_root.is_dir():
        for item in items_from_directory(patch_root, keep_dirs=args.keep_dirs):
            if item.source and item.source.resolve().as_posix() in used:
                continue
            items.append(item)
    if args.verbose:
        print(f"base: {arc.path} (v{arc.version}), {len(items)} item(s)")
    return items


def _cmd_repack(args) -> int:
    items = _items_from_base(args.base, args.patchdir, args)
    version = args.version if args.version is not None else Archive.open(
        args.base, encoding=args.encoding).version
    dest = pack_archive(items, args.archive, version=version, align=args.align,
                        encoding=args.encoding, strict=args.strict)
    if not args.quiet:
        print(f"repacked {len(items)} file(s) into {dest} (MajiroArcV{version}.000)")
    return 0


def _cmd_count(args) -> int:
    """Print only the number of entries — handy for build scripts."""
    print(len(Archive.open(args.archive, encoding=args.encoding).entries))
    return 0


def _cmd_verify(args) -> int:
    arc = Archive.open(args.archive, encoding=args.encoding)
    matching, total = arc.hash_report()
    ok = matching == total and not arc.warnings
    print(f"{arc.path}: v{arc.version}, {total} entries, crc32 ok {matching}/{total}")
    for w in arc.warnings:
        print(f"  warning: {w}")
    if not ok:
        print("  result: SUSPICIOUS")
        return 2
    print("  result: OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="majiro_arc",
        description="Упаковщик/распаковщик архивов .arc движка Majiro",
    )
    p.add_argument("--encoding", default=DEFAULT_ENCODING,
                   help="кодировка имён файлов (по умолчанию cp932)")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--encoding", default=argparse.SUPPRESS,
                        help="кодировка имён файлов (по умолчанию cp932)")

    sp = sub.add_parser("list", help="показать содержимое архива")
    sp.add_argument("archive")
    sp.add_argument("--json", action="store_true", help="вывод в JSON")
    common(sp)
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("info", help="диагностика структуры архива")
    sp.add_argument("archive")
    sp.add_argument("--json", action="store_true", help="вывод в JSON")
    common(sp)
    sp.set_defaults(func=_cmd_info)

    sp = sub.add_parser("verify", help="проверить целостность индекса")
    sp.add_argument("archive")
    common(sp)
    sp.set_defaults(func=_cmd_verify)

    sp = sub.add_parser("count", help="вывести только число файлов (для скриптов)")
    sp.add_argument("archive")
    common(sp)
    sp.set_defaults(func=_cmd_count)

    sp = sub.add_parser("unpack", help="распаковать архив")
    sp.add_argument("archive")
    sp.add_argument("outdir")
    sp.add_argument("--flat", action="store_true", help="игнорировать подкаталоги в именах")
    sp.add_argument("--overwrite", action="store_true", help="перезаписывать файлы")
    sp.add_argument("-q", "--quiet", action="store_true")
    common(sp)
    sp.set_defaults(func=_cmd_unpack)

    sp = sub.add_parser("pack", help="упаковать каталог в архив")
    sp.add_argument("srcdir")
    sp.add_argument("archive")
    sp.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None,
                    help="версия формата (по умолчанию 1, либо как в --base)")
    sp.add_argument("--align", type=int, default=1, metavar="N",
                    help="выравнивание данных, байт (по умолчанию 1 = без выравнивания)")
    sp.add_argument("--keep-dirs", action="store_true",
                    help="сохранять относительные пути (через обратный слэш)")
    sp.add_argument("--no-recursive", action="store_true", help="не заходить в подкаталоги")
    sp.add_argument("--exclude", action="append", default=[], metavar="MASK",
                    help="исключить файлы по маске (можно несколько раз)")
    sp.add_argument("--base", metavar="ARC",
                    help="взять порядок и версию из существующего архива")
    sp.add_argument("--strict", action="store_true", help="ошибка при коллизии хэшей")
    sp.add_argument("-q", "--quiet", action="store_true")
    sp.add_argument("-v", "--verbose", action="store_true")
    common(sp)
    sp.set_defaults(func=_cmd_pack)

    sp = sub.add_parser("repack", help="заменить файлы в существующем архиве")
    sp.add_argument("base", help="исходный архив")
    sp.add_argument("patchdir", help="каталог с новыми файлами")
    sp.add_argument("archive", help="куда записать результат")
    sp.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None,
                    help="версия формата (по умолчанию как в базовом архиве)")
    sp.add_argument("--align", type=int, default=1, metavar="N")
    sp.add_argument("--keep-dirs", action="store_true")
    sp.add_argument("--strict", action="store_true")
    sp.add_argument("-q", "--quiet", action="store_true")
    sp.add_argument("-v", "--verbose", action="store_true")
    common(sp)
    sp.set_defaults(func=_cmd_repack)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MajiroError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # pragma: no cover
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
