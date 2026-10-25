"""Pinned, app-prefix-only repair for Darling's sparse kqueue map walk.

The original close path scans every possible descriptor. These replacements
preserve its callbacks, reference counts and locks, and bound iteration by
the greatest successfully inserted descriptor. See darling_sparse_map.c for
the audited replacement source and its libkqueue license.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile


INSERT_CODE = bytes.fromhex("554889e54883ec4085f6783248813fffffff7f772989f1483b0f77224c8b470831c0f0490fb114c8751448ffc1483b4f10760448894f1031c0e901010000b8ffffffffe9f7000000").ljust(0x13F, b"\x90") + bytes.fromhex("4883c4405dc3")
FOREACH_CODE = bytes.fromhex("554889e54883ec2048897df8488975f0488955e848c745e000000000488b4df8488b01483dffffff7f774948ffc0483b4110480f474110488b7de04839c77334488b5108488b34fa4885f67407488b55e8ff55f048ff45e0ebc2").ljust(0x74, b"\x90") + bytes.fromhex("4883c4205dc3")


@dataclass(frozen=True)
class Site:
    symbol: str
    displacement: int
    size: int
    sha256: str
    replacement: bytes


@dataclass(frozen=True)
class Release:
    size: int
    sha256: str
    patched_sha256: str
    sites: tuple[Site, ...]
    library: str = ""


# x86_64 slices of the two installed universal Darling runtime libraries.
# map_new's existing len remains the inclusive greatest valid descriptor:
# the allocation becomes 24 bytes and the pointer mmap becomes (len+1)*8.
LIBC_RELEASE = Release(
    2975108, "b1a578ba173b705843e113f99348623f8923a57424ee2aac13c13617677ac6e3",
    "a59c162be3a316fcfb25d7a9dcde43c90466ac70c24897642da53b8b1731e692",
    (
        Site("_map_new", 0x12, 1,
             "c555eab45d08845ae9f10d452a99bfcb06f74a50b988fe7e48dd323789b88ee3", b"\x18"),
        Site("_map_new", 0x37, 10,
             "c53d471ce048b4ca7a0b24d1b2e0cb324dc8cb99ed8e405a4d2493f4ca361dab",
             bytes.fromhex("486b75f0084883c60890")),
        Site("_map_new", 0x41, 3,
             "a0f358885d3c9d802edb1cb68f16d5782fba2290f8032e44b8a1ca0d5bc0f47d",
             bytes.fromhex("4531c9")),
        Site("_map_insert", 0, 0x145,
             "755a17758e6f0cd56686d894020be47fd893b217b643c04ef9cbb0ba402b9fc8",
             INSERT_CODE),
        Site("_map_foreach", 0, 0x7A,
             "3cb85c2ecc1343ce711b21f41fc72777e0969e0073258e72a1ef132e168ec5db",
             FOREACH_CODE),
    ),
    "usr/lib/system/libsystem_c.dylib",
)
# The client's active kqueue implementation lives in libSystem.B. Both builds
# use the same frames and instructions; only insert's debug-call RIP offsets
# differ. Independently pin the complete container and changed instruction hash.
SYSTEM_RELEASE = Release(
    244532, "f2caa3b1f39895d7b5c8853907ed73c9a93030b6460a3183318b5cb95b6caf32",
    "1dc68f4c778d557358ea04a5728d5ebecaddc7623fe12f14cd4366ea5251a76b",
    tuple(Site(site.symbol, site.displacement, site.size,
               "ed2c8c111e18ee63ad38e634631404a9ed7eab7f93b04bb7e8b044a68d3991ea"
               if site.symbol == "_map_insert" else site.sha256,
               site.replacement) for site in LIBC_RELEASE.sites),
    "usr/lib/libSystem.B.dylib",
)
RELEASES = (SYSTEM_RELEASE, LIBC_RELEASE)


def _x86_slice(data):
    if data[:4] == b"\xcf\xfa\xed\xfe":
        return 0, data
    if data[:4] != b"\xca\xfe\xba\xbe" or len(data) < 8:
        raise ValueError("Unsupported Mach-O container")
    count, = struct.unpack_from(">I", data, 4)
    if count > 32 or 8 + count * 20 > len(data):
        raise ValueError("Invalid universal header")
    result = None
    ranges = []
    for index in range(count):
        cpu, _, offset, size, alignment = struct.unpack_from(">5I", data, 8 + index * 20)
        if (alignment > 30 or offset % (1 << alignment) or not size
                or offset < 8 + count * 20 or offset + size > len(data)):
            raise ValueError("Invalid universal slice")
        ranges.append((offset, offset + size))
        if cpu == 0x01000007:
            if result is not None:
                raise ValueError("Duplicate x86_64 slice")
            result = offset, data[offset:offset + size]
    if any(a[1] > b[0] for a, b in zip(sorted(ranges), sorted(ranges)[1:])):
        raise ValueError("Overlapping universal slices")
    if result is None:
        raise ValueError("Missing x86_64 slice")
    return result


def _symbol_sites(data, wanted):
    base, image = _x86_slice(data)
    if len(image) < 32:
        raise ValueError("Truncated Mach-O")
    magic, cpu, _, kind, count, command_size, _, _ = struct.unpack_from("<8I", image)
    if (magic != 0xFEEDFACF or cpu != 0x01000007 or kind != 6
            or count > 1024 or 32 + command_size > len(image)):
        raise ValueError("Unsupported Mach-O image")
    position, text, symbols = 32, None, None
    for _ in range(count):
        if position + 8 > 32 + command_size:
            raise ValueError("Truncated load command")
        command, size = struct.unpack_from("<II", image, position)
        if size < 8 or size % 8 or position + size > 32 + command_size:
            raise ValueError("Invalid load command")
        if command == 0x19:
            if size < 72:
                raise ValueError("Truncated segment")
            sections, = struct.unpack_from("<I", image, position + 64)
            if 72 + sections * 80 > size:
                raise ValueError("Truncated sections")
            for index in range(sections):
                section = position + 72 + index * 80
                name = image[section:section + 16].split(b"\0", 1)[0]
                segment = image[section + 16:section + 32].split(b"\0", 1)[0]
                if (name, segment) == (b"__text", b"__TEXT"):
                    address, length, offset = struct.unpack_from("<QQI", image, section + 32)
                    if text is not None or offset + length > len(image):
                        raise ValueError("Invalid text section")
                    text = address, length, offset
        elif command == 2:
            if size != 24 or symbols is not None:
                raise ValueError("Invalid symbol table command")
            symbols = struct.unpack_from("<4I", image, position + 8)
        position += size
    if position != 32 + command_size or text is None or symbols is None:
        raise ValueError("Missing validated layout")
    table, count, strings, strings_size = symbols
    if table + count * 16 > len(image) or strings + strings_size > len(image):
        raise ValueError("Truncated symbols")
    names = image[strings:strings + strings_size]
    found = {}
    address, length, offset = text
    for index in range(count):
        name_index, symbol_type, _, _, value = struct.unpack_from("<IBBHQ", image, table + index * 16)
        if symbol_type & 0xE0 or symbol_type & 0x0E != 0x0E:
            continue
        if name_index >= len(names):
            raise ValueError("Invalid symbol name")
        end = names.find(b"\0", name_index)
        if end < 0:
            raise ValueError("Unterminated symbol")
        name = names[name_index:end].decode("ascii", errors="replace")
        if name in wanted:
            if name in found or value < address or value >= address + length:
                raise ValueError("Ambiguous or misplaced patch symbol")
            found[name] = (base + offset + value - address, base + offset + length)
    if found.keys() != wanted:
        raise ValueError("Missing patch symbol")
    return found


def plan_sparse_map_patch(data, releases=RELEASES, *, library=None):
    """Return (status, replacement) for complete known libraries only."""
    digest = hashlib.sha256(data).hexdigest()
    for release in releases:
        if library is not None and release.library != library:
            continue
        if len(data) != release.size:
            continue
        if digest == release.patched_sha256:
            return "already patched", None
        if digest != release.sha256:
            continue
        try:
            offsets = _symbol_sites(data, {site.symbol for site in release.sites})
            replacement = bytearray(data)
            occupied = set()
            for site in release.sites:
                entry, section_end = offsets[site.symbol]
                start, end = entry + site.displacement, entry + site.displacement + site.size
                if (site.displacement < 0 or not site.size or end > section_end
                        or len(site.replacement) > site.size
                        or hashlib.sha256(data[start:end]).hexdigest() != site.sha256):
                    raise ValueError("Unexpected patch instruction region")
                locations = set(range(start, end))
                if occupied & locations:
                    raise ValueError("Overlapping patch regions")
                occupied |= locations
                replacement[start:end] = site.replacement.ljust(site.size, b"\x90")
            if (release.patched_sha256 and hashlib.sha256(replacement).hexdigest()
                    != release.patched_sha256):
                raise ValueError("Unexpected complete patch result")
            return "patched", bytes(replacement)
        except (ValueError, struct.error):
            break
    return "unsupported Darling library; left unchanged", None


def install_sparse_map_copy(source, destination, *, library=None):
    """Atomically copy a verified repair to an explicit app-prefix path.

    The source is read-only. Unknown destination overrides are preserved.
    Caller chooses the isolated or app-owned prefix; this function has no
    default live prefix and does not stop or modify any running container.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        return "source and prefix destination coincide; left unchanged"
    data = source.read_bytes()
    status, replacement = (plan_sparse_map_patch(data, library=library)
                           if library is not None else plan_sparse_map_patch(data))
    if status == "already patched":
        replacement = data
    elif replacement is None:
        return status
    if destination.is_symlink():
        return "custom Darling library symlink; left unchanged"
    previous = destination.read_bytes() if destination.exists() else None
    if previous is not None:
        existing_status, existing_repair = (plan_sparse_map_patch(previous, library=library)
                                            if library is not None else plan_sparse_map_patch(previous))
        if existing_status == "already patched" and previous == replacement:
            return existing_status
        if existing_status != "patched" or existing_repair != replacement:
            return "custom Darling library override; left unchanged"
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(source.stat().st_mode)
    fd, temporary = tempfile.mkstemp(prefix=".sparse-kqueue-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        if source.read_bytes() != data:
            raise RuntimeError("Darling changed while its prefix copy was being prepared")
        current = destination.read_bytes() if destination.exists() else None
        if destination.is_symlink() or current != previous:
            raise RuntimeError("Darling prefix override changed during preparation")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return status
