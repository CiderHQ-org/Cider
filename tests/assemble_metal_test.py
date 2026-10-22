#!/usr/bin/env python3
"""Assemble owned regression IR into a legacy MTLB, one function per declared stage."""
import hashlib
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

def main():
    source, output = map(Path, sys.argv[1:3])
    functions = [entry.split(":") for entry in sys.argv[3:]] or [["dispatch_probe", "2"]]
    stages = {"0": "vertex", "1": "fragment", "2": "kernel"}
    assert len({kind for _, kind in functions}) == len(functions)

    def tag(name, data):
        return name + struct.pack("<H", len(data)) + data

    entries, codes = [], []
    code_offset = 0
    with tempfile.TemporaryDirectory(prefix="quadra-authored-air-") as tmp:
        for index, (name, kind) in enumerate(functions):
            text = source.read_text()
            if not re.search(r"^source_filename\s*=", text, flags=re.MULTILINE):
                text = 'source_filename = "quadra-authored-regression.ll"\n' + text
            for other in stages.values():
                if other != stages[kind]:
                    text = re.sub(r"^!air\." + other + r"\s*=.*$", "", text, flags=re.MULTILINE)
            ir, bitcode = Path(tmp) / "kernel.ll", Path(tmp) / "kernel.bc"
            ir.write_text(text)
            subprocess.run(["llvm-as", str(ir), "-o", str(bitcode)], check=True)
            code = bitcode.read_bytes()
            tags = b"".join([
                tag(b"NAME", name.encode() + b"\0"), tag(b"TYPE", bytes([int(kind)])),
                tag(b"HASH", hashlib.sha256(code).digest()),
                tag(b"OFFT", struct.pack("<3Q", index*8, index*8, code_offset)),
                tag(b"VERS", bytes([1, 0, 8, 0, 1, 0, 1, 0])), tag(b"MDSZ", struct.pack("<Q", len(code))),
            ]) + b"ENDT"
            entries.append(struct.pack("<I", 4 + len(tags)) + tags)
            codes.append(code)
            code_offset += len(code)
    entry_bytes, code_bytes = b"".join(entries), b"".join(codes)
    public = 88 + 4 + len(entry_bytes)
    private = public + 8*len(functions)
    start = private + 8*len(functions)
    header = b"MTLB\x01\x80\x02\0\x02\0\0\0\0\0\0\0"
    header += struct.pack("<9Q", start + len(code_bytes), 88, len(entry_bytes), public,
                          8*len(functions), private, 8*len(functions), start, len(code_bytes))
    output.write_bytes(header + struct.pack("<I", len(entries)) + entry_bytes
                       + (struct.pack("<I", 8)+b"ENDT")*(2*len(functions)) + code_bytes)


if __name__ == "__main__":
    main()
