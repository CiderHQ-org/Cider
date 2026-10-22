"""Replay locally learned Metal pipeline creations in a bounded, cancellable host process."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

if __package__:
    from . import startup_preload
else:
    import startup_preload

MAX_PIPELINES = 4096
TIMEOUT = 120
STALL_TIMEOUT = 20
MAX_HELPER_RSS = 1536 << 20
STAGE_LIMITS = {"pipelines": MAX_PIPELINES, "libraries": startup_preload.MAX_LIBRARIES,
                "resources": startup_preload.MAX_RESOURCE_FILES}


def recorded(environment):
    """Count this client's descriptions without reading shader contents."""
    if environment.get("MACOBLOX_METAL_PRELOAD") == "0":
        return 0
    root = environment.get("MACOBLOX_METAL_SHADER_CACHE")
    if not root:
        return 0
    scope = hashlib.sha256(environment.get("MACOBLOX_METAL_PRELOAD_KEY", "unscoped").encode()).hexdigest()
    try:
        count = 0
        for path in (Path(root) / "quadra-preload-v1").glob(f"pipeline-{scope}-*.qmc"):
            if path.is_file():
                count += 1
                if count == MAX_PIPELINES:
                    break
        return count
    except OSError:
        return 0


def _stop(process):
    """Stop the helper and its children before the caller launches the game."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit while a descendant still owns the progress pipes. Kill the group
    # even when poll() already reports the leader's exit; waiting only for it leaks work.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("The shader preload helper did not stop; close it before launching Roblox.") from error


def run(library, environment, progress=None, cancel=None, timeout=TIMEOUT, maximum=MAX_PIPELINES,
        *, library_pack=None, resource_root=None, stage_progress=None):
    """Return counts/status. Cache/driver failures are nonfatal; new shaders can still compile
    in the game. Skip and timeout end the whole helper before returning. progress(done,total).
    """
    if environment.get("MACOBLOX_METAL_PRELOAD") == "0":
        return {"status": "disabled", "completed": 0, "total": 0, "failed": 0}
    total = recorded(environment)
    if not total and library_pack is None and resource_root is None:
        return {"status": "empty", "completed": 0, "total": 0, "failed": 0}
    if cancel is not None and cancel.is_set():
        return {"status": "skipped", "completed": 0, "total": total, "failed": 0}
    result = {"status": "failed", "completed": 0, "total": total, "failed": 0}
    extended = library_pack is not None or resource_root is not None
    if extended:
        result["stages"] = {}
    available = startup_preload.available_memory()
    if available is not None and available < startup_preload.MEMORY_RESERVE:
        return {**result, "status": "memory-limited"}
    memory_limit = min(MAX_HELPER_RSS, available // 4) if available is not None else 512 << 20
    child_environment = {key: value for key, value in environment.items() if key != "LD_PRELOAD"}
    # Diagnostics describe the game. The preload helper has its own progress/counts and must
    # not interleave its device's snapshots with the gameplay trace.
    child_environment["MACOBLOX_METAL_DIAGNOSTICS"] = "0"
    child_environment["MACOBLOX_METAL_PRELOAD_IN_PROCESS"] = "0"
    if progress and not extended:
        progress(0, total)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(library),
               str(max(1, min(int(maximum), MAX_PIPELINES)))]
    for option, path in (("--shader-pack", library_pack), ("--resources", resource_root)):
        if path is not None:
            command.extend((option, str(path)))
    try:
        process = subprocess.Popen(command,
                                   env=child_environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as error:
        return {**result, "reason": str(error)}
    deadline = time.monotonic() + max(0, timeout)
    buffers = {}
    last_progress = 0.0
    last_activity = time.monotonic()
    last_memory_check = 0.0
    last_stage = None
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
                buffers[stream] = bytearray()
            while selector.get_map() or process.poll() is None:
                if cancel is not None and cancel.is_set():
                    result["status"] = "skipped"
                    break
                if time.monotonic() >= deadline:
                    result["status"] = "timeout"
                    break
                now = time.monotonic()
                if now - last_activity >= STALL_TIMEOUT:
                    result["status"] = "timeout"
                    break
                if now - last_memory_check >= 0.25:
                    available = startup_preload.available_memory()
                    if (startup_preload.resident_bytes(process.pid) > memory_limit
                            or available is not None and available < startup_preload.MEMORY_RESERVE):
                        result["status"] = "memory-limited"
                        break
                    last_memory_check = now
                for key, _events in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    pending = buffers[key.fileobj]
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending[:] = rest
                        if key.fileobj is not process.stdout or len(line) > 4096:
                            continue
                        try:
                            data = json.loads(line)
                            stage = data.get("phase", "pipelines")
                            if stage not in STAGE_LIMITS:
                                continue
                            done, count, failed = data["completed"], data["total"], data["failed"]
                            if not all(type(value) is int for value in (done, count, failed)):
                                continue
                            if not 0 <= failed <= done <= count <= STAGE_LIMITS[stage]:
                                continue
                        except (ValueError, KeyError, TypeError):
                            continue
                        if stage == "pipelines":
                            result.update(completed=done, total=count, failed=failed)
                        if extended:
                            summary = {"completed": done, "total": count, "failed": failed}
                            for name in ("prepared", "input_bytes", "read_bytes", "budget_bytes"):
                                value = data.get(name)
                                if type(value) is int and 0 <= value <= startup_preload.MAX_PACK_BYTES:
                                    summary[name] = value
                            if data.get("stage_status") in ("complete", "partial", "limited", "failed"):
                                summary["status"] = data["stage_status"]
                            # Final pipeline summaries do not erase completed stage statistics.
                            result["stages"].setdefault(stage, {}).update(summary)
                        final = data.get("status") in ("complete", "partial")
                        if final:
                            result["status"] = data["status"]
                        now = time.monotonic()
                        last_activity = now
                        if not (final and extended) and (done == count or stage != last_stage or now - last_progress >= 0.1):
                            if stage_progress:
                                stage_progress(stage, done, count)
                            elif progress:
                                progress(done, count)
                            last_progress = now
                            last_stage = stage
                    if len(pending) > 8192:
                        del pending[:-4096]
            if result["status"] not in ("skipped", "timeout", "memory-limited"):
                process.wait(timeout=5)
                if process.returncode:
                    result["status"] = "failed"
    finally:
        _stop(process)
        process.stdout.close()
        process.stderr.close()
    return result


def _worker(library, maximum, library_pack=None, resource_root=None):
    host = ctypes.CDLL(library)
    entry = host.quadra_metal_host_api
    entry.argtypes, entry.restype = (ctypes.c_uint32,), ctypes.c_void_p
    api = entry(2)
    if not api:
        raise RuntimeError("the shader preloader requires the matching ABI 2 Metal host")
    size = ctypes.cast(api, ctypes.POINTER(ctypes.c_uint32))[1]
    if size < 8 + 19 * ctypes.sizeof(ctypes.c_void_p):
        raise RuntimeError("the Metal host API table is truncated")
    words = ctypes.cast(api + 8, ctypes.POINTER(ctypes.c_void_p))
    last_error = ctypes.CFUNCTYPE(ctypes.c_char_p)(words[0])
    release = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(words[1])
    create = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(words[2])
    # ABI 2's library_new is pointer 18, after the resource constructors. Reject a short
    # prefix before reading it; no guest pointers cross into this worker.
    library_new = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64)(words[18])
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    latest = {"completed": 0, "total": 0, "failed": 0}

    def report(stage, done, total, failed):
        print(json.dumps({"phase": stage, "completed": done, "total": total, "failed": failed}), flush=True)

    def stage_result(stage, summary):
        print(json.dumps({"phase": stage, **summary, "stage_status": summary["status"], "status": "progress"}), flush=True)

    @callback_type
    def progress(done, total, failed, _context):
        latest.update(completed=done, total=total, failed=failed)
        report("pipelines", done, total, failed)

    device = create(None)
    if not device:
        raise RuntimeError("the preload device is unavailable")
    stages = {}
    try:
        if library_pack is not None:
            def prepare(data):
                buffer = ctypes.create_string_buffer(data)
                handle = library_new(device, buffer, len(data))
                if handle:
                    release(handle)
                return bool(handle)
            try:
                stages["libraries"] = startup_preload.prepare_libraries(library_pack, prepare,
                    lambda done, total, failed: report("libraries", done, total, failed))
            except (OSError, ValueError):
                stages["libraries"] = {"completed": 1, "total": 1, "failed": 1, "status": "failed"}
            stage_result("libraries", stages["libraries"])
        report("pipelines", 0, 0, 0)
        preload = getattr(host, "quadra_metal_host_preload_device", None)
        if preload is not None:
            preload.argtypes, preload.restype = (ctypes.c_void_p, callback_type, ctypes.c_void_p, ctypes.c_uint32), ctypes.c_int
            count = preload(device, progress, None, maximum)
        else:
            preload = host.quadra_metal_host_preload
            preload.argtypes, preload.restype = (callback_type, ctypes.c_void_p, ctypes.c_uint32), ctypes.c_int
            count = preload(progress, None, maximum)
        if count < 0:
            raise RuntimeError((last_error() or b"shader preload failed").decode(errors="replace"))
    finally:
        release(device)
    if resource_root is not None:
        stages["resources"] = startup_preload.warm_resources(resource_root,
            lambda done, total, failed: report("resources", done, total, failed))
        stage_result("resources", stages["resources"])
    partial = latest["failed"] or any(s["status"] in ("partial", "failed") for s in stages.values())
    print(json.dumps({**latest, "status": "partial" if partial else "complete"}), flush=True)


if __name__ == "__main__":
    try:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--worker", required=True)
        parser.add_argument("maximum", type=int)
        parser.add_argument("--shader-pack", type=Path)
        parser.add_argument("--resources", type=Path)
        arguments = parser.parse_args()
        _worker(arguments.worker, max(1, min(arguments.maximum, MAX_PIPELINES)), arguments.shader_pack, arguments.resources)
    except Exception as error:
        print(f"Shader preloading unavailable: {error}", file=sys.stderr)
        sys.exit(2)
