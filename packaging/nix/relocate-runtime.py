"""Relocate CiderDarling's embedded Linux install paths into the FHS tree.

Keep ELF offsets and compiled std::string lengths intact with equal-length paths.
Only host ELF programs are changed; guest Mach-O install names stay intact.
"""
from pathlib import Path
import sys


def relocate(data, prefix, replacement):
    prefix, replacement = prefix.encode(), replacement.encode()
    if len(prefix) != len(replacement):
        raise ValueError('Runtime prefixes must have equal byte lengths')
    return data.replace(prefix, replacement)


def main():
    root, prefix, replacement = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            elf = stream.read(4) == b"\x7fELF"
        if elf:
            data = path.read_bytes()
            updated = relocate(data, prefix, replacement)
            if updated != data:
                path.write_bytes(updated)


if __name__ == "__main__":
    main()
