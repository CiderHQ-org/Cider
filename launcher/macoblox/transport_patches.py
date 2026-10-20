"""Verified RakNet compatibility patches for known client executables.

Offsets and instructions were inspected in the x86_64 7411056, 7421053, 7431129,
7431134 and 7441080 releases downloaded from Roblox's deployment CDN.
Normalize only the listed patches before checking the complete executable's
SHA-256. A client update or an unexpected modification is unsupported; no
heuristic search or partial application is allowed.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile


@dataclass(frozen=True)
class Site:
    offset: int
    original: bytes
    patched: bytes
    name: str


@dataclass(frozen=True)
class Release:
    size: int
    sha256: str
    sites: tuple[Site, ...]
    compatible_changes: tuple[Site, ...] = ()


RELEASES = (Release(
    123526704,
    "be95441279431786043ca06a918b1c3ef172f54848b716df8ecf2e440921ebff",
    (
        Site(0x4A38D78, bytes.fromhex("554889e5"), bytes.fromhex("31c0c390"), "transport selection"),
        Site(0x536EC65, b"\x01", b"\xff", "fallback connection"),
        Site(0x5370858, b"\x75", b"\xeb", "dummy connection first caller"),
        Site(0x5370A1E, b"\x75", b"\xeb", "dummy connection second caller"),
    ),
    (Site(0x1153F70, b"\x89\xf3", b"\x31\xdb", "startup throttle"),),
), Release(
    # 0.742.0.7421053, official upload version-f9247f9560044102.
    # Each relocated site was inspected with its branch target and flag;
    # the size/hash below describe the pristine executable in that archive.
    125285200,
    "ac9ad59b3aa3805bf2d1c89fb6ff9c7941bf2e57af17a81cbc26abe94a022c47",
    (
        Site(0x4B5D12B, bytes.fromhex("554889e5"), bytes.fromhex("31c0c390"), "transport selection"),
        Site(0x54B2F8D, b"\x01", b"\xff", "fallback connection"),
        Site(0x54B4B80, b"\x75", b"\xeb", "dummy connection first caller"),
        Site(0x54B4D46, b"\x75", b"\xeb", "dummy connection second caller"),
    ),
    (Site(0x11A21C8, b"\x89\xf3", b"\x31\xdb", "startup throttle"),),
), Release(
    # 0.743.0.7431129, official upload version-f641ec9ebf6145c3.
    # Shared-client configuration adds another early/late dummy path. Skip
    # both early paths to 0x105578cf5 after the empty optional state is set;
    # keep the late caller on its cleanup path at 0x105578ee5. Neither path
    # creates a dummy connection, regardless of either flag's value.
    126617760,
    "eca680dd03cd93981b1bbd3a5b628c7be9533f81abad541d1e2f572ea06ffa88",
    (
        Site(0x4BF0193, bytes.fromhex("554889e5"), bytes.fromhex("31c0c390"), "transport selection"),
        Site(0x5576C8F, b"\x01", b"\xff", "fallback connection"),
        Site(0x5578AA3, bytes.fromhex("0f85e1010000"), bytes.fromhex("e94d02000090"),
             "dummy connection early shared/legacy callers"),
        Site(0x5578EDF, bytes.fromhex("0f8480010000"), bytes.fromhex("909090909090"),
             "dummy connection late shared/legacy callers"),
    ),
    (Site(0x11C9A7C, b"\x89\xf3", b"\x31\xdb", "startup throttle"),),
), Release(
    # 0.743.0.7431134, official upload version-212bac6bdccd4673.
    # Independently checked against the pristine deployment archive. These
    # functions retain 7431129's control flow but have relocated code/data.
    # Skip both early dummy paths to 0x10557aba5 after optional-state setup;
    # keep the late caller on its cleanup path at 0x10557ad95.
    126626048,
    "3f1098053bae2717a10842120ba38a91477a465204014acf469676921f98eea3",
    (
        Site(0x4BF208B, bytes.fromhex("554889e5"), bytes.fromhex("31c0c390"), "transport selection"),
        Site(0x5578B3F, b"\x01", b"\xff", "fallback connection"),
        Site(0x557A953, bytes.fromhex("0f85e1010000"), bytes.fromhex("e94d02000090"),
             "dummy connection early shared/legacy callers"),
        Site(0x557AD8F, bytes.fromhex("0f8480010000"), bytes.fromhex("909090909090"),
             "dummy connection late shared/legacy callers"),
    ),
    (Site(0x11CB3D0, b"\x89\xf3", b"\x31\xdb", "startup throttle"),),
), Release(
    # 0.744.0.7441080, official upload version-546c6da637854de3.
    # Flag registrations and internal branch targets retain 743's transport
    # control flow; object fields and code/data addresses have moved. Skip
    # both early dummy paths to 0x1056e7649 after optional-state setup, and
    # keep the late caller on its cleanup path at 0x1056e7839.
    128453408,
    "a901265fc499c0a151dae1809664f7d6b71135ac74044e84076852f008e436d7",
    (
        Site(0x4CEE2E8, bytes.fromhex("554889e5"), bytes.fromhex("31c0c390"), "transport selection"),
        Site(0x56E5595, b"\x01", b"\xff", "fallback connection"),
        Site(0x56E73F7, bytes.fromhex("0f85e1010000"), bytes.fromhex("e94d02000090"),
             "dummy connection early shared/legacy callers"),
        Site(0x56E7833, bytes.fromhex("0f8480010000"), bytes.fromhex("909090909090"),
             "dummy connection late shared/legacy callers"),
    ),
    (Site(0x11F480C, b"\x89\xf3", b"\x31\xdb", "startup throttle"),),
))


def plan_transport_patch(data, releases=RELEASES):
    """Return (status, complete replacement), without mutating anything."""
    for release in releases:
        if len(data) != release.size:
            continue
        normalized = bytearray(data)
        sites = release.sites + release.compatible_changes
        if any(data[s.offset:s.offset + len(s.original)] not in (s.original, s.patched)
               or len(s.original) != len(s.patched) for s in sites):
            continue
        for site in sites:
            normalized[site.offset:site.offset + len(site.original)] = site.original
        if hashlib.sha256(normalized).hexdigest() != release.sha256:
            continue
        replacement = bytearray(data)
        for site in release.sites:
            replacement[site.offset:site.offset + len(site.patched)] = site.patched
        if replacement == data:
            return "already patched", None
        return "patched", replacement
    return "unsupported client; transport binary left unchanged", None


def apply_transport_patch(binary):
    binary = Path(binary)
    data = binary.read_bytes()
    status, replacement = plan_transport_patch(data)
    if replacement is None:
        return status
    file_stat = binary.stat()
    fd, temporary = tempfile.mkstemp(prefix=".RobloxPlayer-transport-", dir=binary.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), stat.S_IMODE(file_stat.st_mode))
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        # An updater or another patcher may have touched the client while the
        # replacement was prepared. Refuse to overwrite its changes.
        if binary.read_bytes() != data:
            raise RuntimeError("The client changed while transport patches were being prepared")
        os.replace(temporary, binary)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return status
