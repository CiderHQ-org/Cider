#!/usr/bin/env python3
"""Optional native Wayland AppKit fixture; never uses an installed prefix.

Run after other desktop tests stop:
  python tests/run_darling_wayland_render.py --build-dir /path/to/shim/build
Use --compile-only to compile without opening a window or starting Darling.
--output-dir keeps the binary and nonsecret evidence; prefixes stay in /tmp.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
from macoblox import display, graphics, runtime


def parent_resize_evidence(text):
    """Compare Cocoa sizes with actual committed SHM buffers on xdg parents."""
    buffers, pending, committed, parents, checks = {}, {}, {}, set(), []
    ident = r"[#@](\d+)"
    for line in text.splitlines():
        match = re.search(r"get_xdg_surface\(new id xdg_surface" + ident +
                          r", wl_surface" + ident + r"\)", line)
        if match:
            parents.add(match[2])
        match = re.search(r"create_buffer\(new id wl_buffer" + ident +
                          r", \d+, (\d+), (\d+), \d+, [01]\)", line)
        if match:
            buffers[match[1]] = (int(match[2]), int(match[3]))
        match = re.search(r"wl_surface" + ident + r"\.attach\(wl_buffer" + ident + r",", line)
        if match and match[2] in buffers:
            pending[match[1]] = buffers[match[2]]
        match = re.search(r"wl_surface" + ident + r"\.commit\(\)", line)
        if match and match[1] in pending:
            committed[match[1]] = pending.pop(match[1])
        match = re.search(r"RESIZE_EXPECT ([01]) (\d+) (\d+)", line)
        if match:
            expected = (int(match[2]), int(match[3]))
            checks.append({"fullscreen": bool(int(match[1])), "expected": expected,
                           "parent_committed": any(committed.get(parent) == expected for parent in parents)})
    return checks


def run_case(binary, build, output, negative, renderer="vulkan", client="darling"):
    name = "failed-init-retry" if negative else "render"
    prefix = Path(tempfile.mkdtemp(prefix="macoblox-wayland-fixture-")) / "prefix"
    for relative in ("var/run", "var/db", "var/log", "var/tmp/launchd", "private/var/run",
                     "private/var/log", "private/tmp", "private/etc"):
        (prefix / relative).mkdir(parents=True, exist_ok=True)
    base = {key: value for key, value in os.environ.items() if key not in
            ("DPREFIX", "DISPLAY", "DYLD_INSERT_LIBRARIES", "DYLD_FORCE_FLAT_NAMESPACE", "MACOBLOX_WEB_SOCKET")}
    overrides = {}
    if negative:
        invalid = prefix.parent / "invalid_icd.json"
        invalid.write_text(json.dumps({"file_format_version": "1.0.1", "ICD": {
            "library_path": str(prefix.parent / "missing-driver.so"), "api_version": "1.3.0"}}))
        overrides["VK_DRIVER_FILES"] = str(invalid)
    with patch.dict(os.environ, overrides):
        values = graphics.renderer_environment(renderer)
        values.update(display.window_environment({"renderer": renderer, "display_backend": "wayland"},
                                                 build / "libmacoblox-wayland.so"))
    values.update({"MACOBLOX_TRACE_WAYLAND": "1", "WAYLAND_DEBUG": "client", "DYLD_FORCE_FLAT_NAMESPACE": "1",
                   "DYLD_INSERT_LIBRARIES": "/Volumes/SystemRoot" + str(build / "libMacOBloxShims.dylib"),
                   "MESA_SHADER_CACHE_DIR": str(output / "mesa-cache"),
                   "__GL_SHADER_DISK_CACHE_PATH": str(output / "nvidia-cache")})
    # LD_PRELOAD may contain Darling's required no-root helper. Keep it on
    # the darling launcher; do not forward it to the native fixture itself.
    environment = {**base, **values, "DPREFIX": str(prefix)}
    arguments = ["/Volumes/SystemRoot" + str(binary)]
    if negative:
        arguments.append("--expect-init-failure")
    elif renderer == "opengl":
        arguments.append("--opengl")
    command = [client, "shell", "/bin/bash", "-c",
               'unset DISPLAY MACOBLOX_WEB_SOCKET LD_PRELOAD; exec /usr/bin/env "$@"',
               "wayland-fixture", *[f"{key}={value}" for key, value in values.items()], *arguments]
    log_path = output / f"{name}.log"
    evidence = {"prefix": str(prefix), "no_auth": True, "display_unset": True,
                "negative_control": negative, "renderer": renderer,
                "generated_icd": values.get("VK_ADD_DRIVER_FILES")}
    try:
        with log_path.open("w") as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=45)
        evidence["returncode"] = result.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        evidence["error"] = str(error)
    finally:
        try:
            result = subprocess.run([client, "shutdown"], env={**base, "DPREFIX": str(prefix)},
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
            evidence["scoped_shutdown_returncode"] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            evidence["shutdown_error"] = str(error)
    text = log_path.read_text(errors="replace") if log_path.is_file() else ""
    expected = "RETRY_PASS failures=2" if negative else "PASS: Native Wayland AppKit"
    if not negative:
        evidence["resize_checks"] = parent_resize_evidence(text)
    resize_passed = negative or (len(evidence["resize_checks"]) == 2 and
                                 all(check["parent_committed"] for check in evidence["resize_checks"]))
    evidence["passed"] = (evidence.get("returncode") == 0 and expected in text and
                          evidence.get("scoped_shutdown_returncode") == 0 and resize_passed)
    (output / f"{name}.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))
    for line in text.splitlines():
        if any(token in line for token in ("_RENDERER", "INIT_FAILURE", "RETRY_", "IDENTITY_", "PUMP_", "POINTER_PASS", "HID_PASS", "RESIZE_", "PASS:", "FAIL:")):
            print(line)
    return evidence["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--sysroot", type=Path)
    parser.add_argument("--darling", help="Darling executable matching --sysroot; defaults to Cider's selected runtime")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--renderer", choices=("opengl", "vulkan"), default="vulkan")
    args = parser.parse_args()
    selected = runtime.resolve_runtime()
    sysroot = args.sysroot or Path(os.environ.get("DARLING_SYSROOT", selected["sysroot"]))
    client = args.darling or selected["executable"]
    build = args.build_dir.resolve()
    for name in ("libMacOBloxShims.dylib", "libmacoblox-wayland.so"):
        if not (build / name).is_file():
            parser.error(f"Missing build artifact: {build / name}")
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix="macoblox-wayland-evidence-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / "darling-wayland-render-test"
    result = subprocess.run(["clang", "-target", "x86_64-apple-darwin", "-fuse-ld=lld",
                             "-isysroot", str(sysroot), "-mmacosx-version-min=11.0", "-fobjc-exceptions",
                             "-Wall", "-Wextra", str(ROOT / "tests/darling_wayland_render_test.m"),
                             "-framework", "AppKit", "-framework", "Foundation", "-framework", "OpenGL",
                             "-framework", "CoreGraphics", "-framework", "IOKit", "-o", str(binary)], timeout=30)
    if result.returncode:
        return result.returncode
    if args.compile_only:
        print(json.dumps({"compile_only": True, "binary": str(binary)}))
        return 0
    if not os.environ.get("WAYLAND_DISPLAY"):
        parser.error("This fixture requires a running native Wayland desktop session")
    os.environ["XDG_CACHE_HOME"] = str(output / "driver-cache")
    positive = run_case(binary, build, output, False, args.renderer, client)
    negative = run_case(binary, build, output, True, "vulkan", client) if args.renderer == "vulkan" else True
    return 0 if positive and negative else 1


if __name__ == "__main__":
    raise SystemExit(main())
