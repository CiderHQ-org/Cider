"""Bounded readers for installed shader libraries and local resource file warming.

No downloads, GPU asset uploads or shader/state guesses. Client bytes stay local.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
import time

MAX_PACK_BYTES = 256 << 20
MAX_LIBRARY_BYTES = 64 << 20
MAX_LIBRARY_INPUT = 128 << 20
MAX_LIBRARIES = 4096
MAX_PACK_ENTRIES = 32768
MAX_RESOURCE_FILES = 4096
MAX_SCAN = 8192
MAX_RESOURCE_BYTES = 128 << 20
MEMORY_RESERVE = 768 << 20
RESOURCE_SECONDS = 3
RESOURCE_SUFFIXES = frozenset((".ttf", ".otf", ".dds", ".tex", ".ktx", ".ktx2", ".png",
                               ".jpg", ".jpeg", ".mesh", ".rbxm", ".rbxmx", ".ogg", ".mp3", ".wav"))


def available_memory():
    """The smaller of MemAvailable and remaining Linux cgroup-v2 ancestor limits."""
    limits = []
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                limits.append(int(line.split()[1]) * 1024)
                break
    except (OSError, ValueError, IndexError):
        pass
    try:
        group = next(line[4:] for line in Path("/proc/self/cgroup").read_text().splitlines()
                     if line.startswith("0::/"))
        root = Path("/sys/fs/cgroup")
        directory = root / group
        if ".." in directory.parts:
            return min(limits) if limits else None
        while True:
            for name in ("memory.max", "memory.high"):
                try:
                    maximum = int((directory / name).read_text())
                    current = int((directory / "memory.current").read_text())
                    limits.append(max(0, maximum - current))
                except (OSError, ValueError):
                    pass
            if directory == root:
                break
            directory = directory.parent
    except (OSError, StopIteration):
        pass
    return min(limits) if limits else None


def resident_bytes(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def resource_budget(available):
    if available is None:
        return 32 << 20
    return min(MAX_RESOURCE_BYTES, available // 16, max(0, available - MEMORY_RESERVE))


def _open_regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("preload input is not a regular file")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def library_ranges(stream):
    """Validate RBXS v11 tables and return bounded unique payload ranges, without names."""
    length = os.fstat(stream.fileno()).st_size
    header = stream.read(20)
    if len(header) != 20 or length > MAX_PACK_BYTES:
        raise ValueError("shader pack has an invalid size")
    magic, version, variants, defines, options, names, count, _ = struct.unpack("<4s6HI", header)
    if magic != b"RBXS" or version != 11 or not variants or not names or not 0 < count <= MAX_PACK_ENTRIES:
        raise ValueError("unsupported shader pack layout")
    table = 20 + variants * 64 + names * 68 + defines * 64 + options * 65
    source = table + count * 64
    if source > length:
        raise ValueError("shader pack tables exceed the file")
    stream.seek(table)
    entries = stream.read(count * 64)
    if len(entries) != count * 64:
        raise ValueError("shader pack changed during preparation")
    ranges = set()
    for index in range(count):
        offset, size = struct.unpack_from("<II", entries, index * 64 + 16)
        stage, variant, name = struct.unpack_from("<BBH", entries, index * 64 + 28)
        if (stage not in b"vpc" or variant >= variants or name >= names or not size
                or size > MAX_LIBRARY_BYTES or offset < source or offset + size > length):
            raise ValueError("shader pack payload exceeds its bounds")
        ranges.add((offset, size))
    ordered = sorted(ranges)
    for (offset, size), (following, _) in zip(ordered, ordered[1:]):
        if offset + size > following:
            raise ValueError("shader pack payloads overlap")
    return ordered[:MAX_LIBRARIES]


def _library(payload):
    # Payloads include client metadata before their Metal container. Accept only a bounded
    # container whose own sections fit; the existing native loader validates its contents.
    position = 0
    for _ in range(8):
        start = payload.find(b"MTLB", position)
        if start < 0:
            break
        if start + 88 <= len(payload):
            fields = struct.unpack_from("<9Q", payload, start + 16)
            size = fields[0]
            if (88 <= size <= len(payload) - start
                    and all(offset <= size and length <= size - offset
                            for offset, length in zip(fields[1::2], fields[2::2]))):
                return payload[start:start + size]
        position = start + 4
    raise ValueError("payload has no bounded Metal library")


def prepare_libraries(path, prepare, progress):
    """prepare(bytes) loads/releases one library through the normal host ABI."""
    with _open_regular(path) as stream:
        ranges = library_ranges(stream)
        total = len(ranges)
        progress(0, total, 0)
        seen = set()
        read = failed = completed = prepared = 0
        for offset, size in ranges:
            if read + size > MAX_LIBRARY_INPUT:
                break
            stream.seek(offset)
            payload = stream.read(size)
            read += len(payload)
            completed += 1
            try:
                if len(payload) != size:
                    raise ValueError("shader pack changed during preparation")
                data = _library(payload)
                key = hashlib.sha256(data).digest()
                if key not in seen:
                    if not prepare(data):
                        raise ValueError("host could not prepare this library")
                    seen.add(key)
                    prepared += 1
            except (OSError, ValueError):
                failed += 1
            progress(completed, total, failed)
    return {"completed": completed, "total": total, "failed": failed, "prepared": prepared,
            "input_bytes": read, "status": "limited" if completed < total else "partial" if failed else "complete"}


def resource_files(root):
    root = Path(root)
    directories = [root / name for name in ("content", "PlatformContent", "ExtraContent")]
    files = []
    scanned = 0
    while directories and scanned < MAX_SCAN and len(files) < MAX_RESOURCE_FILES:
        directory = directories.pop()
        try:
            if directory.is_symlink():
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if entry.is_dir(follow_symlinks=False) and len(directories) < 256:
                        directories.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in RESOURCE_SUFFIXES:
                        files.append(Path(entry.path))
                    if scanned >= MAX_SCAN or len(files) >= MAX_RESOURCE_FILES:
                        break
        except OSError:
            continue
    # Warm fonts and native textures before the larger collection of small images/models.
    return sorted(files, key=lambda p: (p.suffix.lower() not in (".ttf", ".otf", ".dds", ".tex"), str(p)))


def warm_resources(root, progress, maximum=None, seconds=RESOURCE_SECONDS):
    files = resource_files(root)
    budget = resource_budget(available_memory())
    if maximum is not None:
        budget = min(budget, max(0, maximum))
    deadline = time.monotonic() + max(0, seconds)
    read = failed = completed = 0
    progress(0, len(files), 0)
    for path in files:
        if read >= budget or time.monotonic() >= deadline:
            break
        try:
            with _open_regular(path) as stream:
                while read < budget and time.monotonic() < deadline:
                    chunk = stream.read(min(256 << 10, budget - read))
                    read += len(chunk)
                    if not chunk:
                        break
        except (OSError, ValueError):
            failed += 1
        completed += 1
        progress(completed, len(files), failed)
    limited = read >= budget or completed < len(files)
    return {"completed": completed, "total": len(files), "failed": failed, "read_bytes": read,
            "budget_bytes": budget, "status": "limited" if limited else "partial" if failed else "complete"}
