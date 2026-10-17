#!/usr/bin/env python3
"""Optional AppKit keyboard regression in a fresh prefix on a Wayland display.

Prefer a disposable compositor. Synthetic SDL events affect only the fixture's
window. The extra injection export is built into a test-only helper; production
artifacts and the installed prefix are never modified. --compile-only needs no
compositor. Pass --sysroot/--darling when using a different runtime.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
from macoblox import display, graphics, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--sysroot", type=Path)
    parser.add_argument("--darling")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    selected = runtime.resolve_runtime()
    sysroot = args.sysroot or Path(selected["sysroot"])
    client = args.darling or selected["executable"]
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix="cider-keyboard-evidence-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    build = output / "test-helper"
    build.mkdir(exist_ok=True)
    shutil.copy2(args.build_dir.resolve() / "libMacOBloxShims.dylib", build / "libMacOBloxShims.dylib")
    libraries = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "sdl2", "wayland-client", "wayland-egl", "wayland-cursor"], text=True))
    subprocess.run(["clang++", "-std=c++17", "-O2", "-fPIC", "-shared", "-pthread",
                    str(ROOT / "tests/wayland_keyboard_host_fixture.cpp"), *libraries,
                    "-o", str(build / "libmacoblox-wayland.so")], check=True, timeout=30)
    literal_flags = []
    if subprocess.run(["clang", "-target", "x86_64-apple-darwin", "-fno-objc-constant-literals",
                       "-x", "objective-c", "-fsyntax-only", "/dev/null"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        literal_flags = ["-fno-objc-constant-literals"]
    binary = output / "darling-keyboard-test"
    subprocess.run(["clang", "-target", "x86_64-apple-darwin", "-fuse-ld=lld", "-isysroot", str(sysroot),
                    "-mmacosx-version-min=11.0", "-fobjc-exceptions", *literal_flags,
                    "-Wl,-undefined,dynamic_lookup", str(ROOT / "tests/darling_wayland_keyboard_test.m"),
                    "-framework", "AppKit", "-framework", "Foundation", "-framework", "CoreGraphics",
                    "-o", str(binary)], check=True, timeout=30)
    if args.compile_only:
        print(f"Compiled keyboard fixture and test-only helper: {output}")
        return 0
    if not os.environ.get("WAYLAND_DISPLAY"):
        parser.error("A Wayland display is required; use a private compositor or --compile-only")
    # Keep every process in a fresh, uniquely named prefix. Never reuse DPREFIX.
    prefix = Path(tempfile.mkdtemp(prefix="cider-keyboard-prefix-")) / "prefix"
    values = graphics.renderer_environment("opengl")
    values.update(display.window_environment({"renderer": "opengl", "display_backend": "wayland"},
                                             build / "libmacoblox-wayland.so"))
    values.update({"DYLD_FORCE_FLAT_NAMESPACE": "1",
                   "DYLD_INSERT_LIBRARIES": "/Volumes/SystemRoot" + str(build / "libMacOBloxShims.dylib")})
    environment = {key: value for key, value in os.environ.items() if key not in
                   ("DPREFIX", "DISPLAY", "DYLD_INSERT_LIBRARIES", "MACOBLOX_WEB_SOCKET")}
    environment.update(values, DPREFIX=str(prefix))
    command = [client, "shell", "/bin/bash", "-c",
               'unset DISPLAY MACOBLOX_WEB_SOCKET LD_PRELOAD; exec /usr/bin/env "$@"', "keyboard-test",
               *[f"{key}={value}" for key, value in values.items()], "/Volumes/SystemRoot" + str(binary)]
    log_path = output / "keyboard.log"
    try:
        with log_path.open("w") as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=40)
    finally:
        subprocess.run([client, "shutdown"], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    text = log_path.read_text(errors="replace")
    for line in text.splitlines():
        if "PASS:" in line or "FAIL line" in line:
            print(line)
    print(f"Evidence: {log_path}")
    return 0 if result.returncode == 0 and "PASS: real AppKit" in text else 1


if __name__ == "__main__":
    raise SystemExit(main())
