"""Verified source whitespace repair for the known RBXS v11 GLSL pack.

The 7411056 client's source parser mistakes every literal ``uniform vec4``
declaration for a CB constant buffer. Two HeightmapDebugPS sources also have
ordinary lookup arrays. Changing the space after ``uniform`` to a tab keeps
the GLSL tokens, names, array sizes, pack offsets and cache keys unchanged,
while allowing those arrays to reach the OpenGL compiler.

Only the complete known pack, or its four supported whitespace changes, is
accepted. Unknown packs and any other modifications are left unchanged.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile


@dataclass(frozen=True)
class Source:
    offset: int
    size: int
    sha256: str
    descriptors: tuple[int, ...]
    sites: tuple[int, ...]  # Byte offsets relative to this source.


@dataclass(frozen=True)
class Release:
    size: int
    sha256: str
    sources: tuple[Source, ...]


RELEASES = (Release(
    4368535,
    "736943d1dd2881451292eab34c892dec0cd146b5e4cb0b6770abc2f282afc5c6",
    (
        Source(0x37D917, 21402,
               "9f113af818c8b2df6a584edc16f323326878cf9d20ef5e034790c9a69d2573df",
               (2538, 2539, 2540), (0x52C, 0x54B)),
        Source(0x382CB1, 21572,
               "9d13523b7b5076b2949bad827db313204a074e27720e978332227721e261b4bd",
               (2541,), (0x52C, 0x54B)),
    ),
), Release(
    # Official 0.742.0.7421053 pack: identical affected sources, moved tables.
    4558808,
    "70c10f51c054748e409e7e8bca3ed894052c08718f34ba37c9dbc482358216df",
    (
        Source(0x3A4036, 21402,
               "9f113af818c8b2df6a584edc16f323326878cf9d20ef5e034790c9a69d2573df",
               (2568, 2569, 2570), (0x52C, 0x54B)),
        Source(0x3A93D0, 21572,
               "9d13523b7b5076b2949bad827db313204a074e27720e978332227721e261b4bd",
               (2571,), (0x52C, 0x54B)),
    ),
), Release(
    # Official 0.744.0.7441080 pack, upload version-546c6da637854de3.
    # Both affected sources are unchanged; the descriptor/source tables moved.
    4561972,
    "911fd9000641a4181b6ab45741b05d67a963639936cb65edba14505727557528",
    (
        Source(0x39E43C, 21402,
               "9f113af818c8b2df6a584edc16f323326878cf9d20ef5e034790c9a69d2573df",
               (2565, 2566, 2567), (0x52C, 0x54B)),
        Source(0x3A37D6, 21572,
               "9d13523b7b5076b2949bad827db313204a074e27720e978332227721e261b4bd",
               (2568,), (0x52C, 0x54B)),
    ),
))


def _validate_layout(data, sources):
    """Check the loader's fixed tables and all shared source ranges."""
    if len(data) < 20:
        return False
    magic, version, variants, defines, options, names, shaders, _ = struct.unpack_from(
        "<4s6HI", data)
    if magic != b"RBXS" or version != 11 or not variants or not names or not shaders:
        return False
    names_start = 20 + variants * 64
    table_start = names_start + names * 68 + defines * 64 + options * 65
    source_start = table_start + shaders * 64
    if source_start >= len(data):
        return False
    ranges = {}
    for index in range(shaders):
        entry = table_start + index * 64
        offset, size = struct.unpack_from("<II", data, entry + 16)
        kind, variant, name_index = struct.unpack_from("<BBH", data, entry + 28)
        if (kind not in b"vpc" or variant >= variants or name_index >= names
                or not size or offset < source_start or offset + size > len(data)):
            return False
        name_start = names_start + name_index * 68
        name = data[name_start:name_start + 64].split(b"\0", 1)[0]
        ranges.setdefault((offset, size), []).append((index, name))
    position = source_start
    for offset, size in sorted(ranges):
        if offset != position:
            return False
        position += size
    if position != len(data):
        return False
    for source in sources:
        references = ranges.get((source.offset, source.size), [])
        if (tuple(index for index, _ in references) != source.descriptors
                or any(name != b"HeightmapDebugPS" for _, name in references)):
            return False
        blob = data[source.offset:source.offset + source.size]
        if hashlib.sha256(blob).hexdigest() != source.sha256:
            return False
        # The repair is restricted to the two ordinary lookup declarations.
        # Constant buffers retain their original whitespace and parser path.
        for site, declaration in zip(source.sites, (
                b"uniform vec4 MaterialLUT[256];", b"uniform vec4 ColorLUT[256];")):
            if site < 7 or blob[site - 7:site - 7 + len(declaration)] != declaration:
                return False
        if len(source.sites) != 2:
            return False
    return True


def plan_shader_patch(data, releases=RELEASES):
    """Return (status, complete replacement), without changing a file."""
    for release in releases:
        if len(data) != release.size:
            continue
        normalized = bytearray(data)
        positions = [source.offset + site for source in release.sources for site in source.sites]
        if (not positions or len(set(positions)) != len(positions)
                or any(position < 0 or position >= len(data)
                       or data[position] not in (ord(" "), ord("\t")) for position in positions)):
            continue
        for position in positions:
            normalized[position] = ord(" ")
        if (hashlib.sha256(normalized).hexdigest() != release.sha256
                or not _validate_layout(normalized, release.sources)):
            continue
        replacement = bytearray(data)
        for position in positions:
            replacement[position] = ord("\t")
        if replacement == data:
            return "already patched", None
        return "patched", replacement
    return "unsupported shader pack; shader sources left unchanged", None


def apply_shader_patch(pack):
    pack = Path(pack)
    data = pack.read_bytes()
    status, replacement = plan_shader_patch(data)
    if replacement is None:
        return status
    file_stat = pack.stat()
    fd, temporary = tempfile.mkstemp(prefix=".glsl-compat-", dir=pack.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), stat.S_IMODE(file_stat.st_mode))
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        if pack.read_bytes() != data:
            raise RuntimeError("The shader pack changed while its repair was being prepared")
        os.replace(temporary, pack)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return status
