"""Select one Darling executable, its matching root and its own guest prefix."""
import json
import os
from pathlib import Path
import shutil

from .paths import user_directory


def read_selection(path):
    """An explicit selection must never silently fall back to another runtime."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 16384:
            raise ValueError("file is too large")
        data = json.loads(path.read_text())
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or data.get("runtime") not in ("regular", "ciderdarling")):
            raise ValueError("unknown runtime or schema")
        for key in ("executable", "sysroot", "prefix"):
            value = data.get(key)
            if (not isinstance(value, str) or not Path(value).is_absolute()
                    or any(character in value for character in "\n\r\0")):
                raise ValueError(f"invalid {key}")
        return data
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read Darling selection {path}: {error}. Rerun Cider's installer.") from error


def metadata(sysroot):
    try:
        path = Path(sysroot) / "usr/share/ciderdarling/runtime.json"
        if path.stat().st_size > 65536:
            return {}
        data = json.loads(path.read_text())
        if (isinstance(data, dict) and data.get("schema_version") == 1
                and data.get("name") == "CiderDarling"):
            return data
    except (OSError, ValueError):
        pass
    return {}


def resolve_runtime(environment=None, selection_file=None):
    env = os.environ if environment is None else environment
    # A Flatpak carries its own client, sysroot and rootless helper. Host
    # installer preferences cannot select files outside its sandbox.
    flatpak = bool(env.get("FLATPAK_ID"))
    selected = None if flatpak else read_selection(
        selection_file if selection_file is not None else user_directory("CONFIG") / "runtime.json")
    if selected is not None:
        result = dict(selected)
    else:
        executable = shutil.which("darling", path=env.get("PATH")) or "darling"
        roots = [Path("/usr/libexec/darling"), Path("/usr/local/libexec/darling")]
        if executable != "darling":
            roots.insert(0, Path(executable).resolve().parent.parent / "libexec/darling")
        if flatpak:
            roots = [Path("/app/libexec/darling")]
        sysroot = next((path for path in roots if path.is_dir()), roots[0])
        result = {"runtime": "regular", "executable": executable,
                  "sysroot": str(sysroot), "prefix": str(Path.home() / ".darling")}
    if env.get("DPREFIX"):
        result["prefix"] = str(Path(env["DPREFIX"]).absolute())
    result["metadata"] = metadata(result["sysroot"])
    return result


def guest_variables(runtime_metadata):
    # This existing shim switch prevents the binary-scanning trampoline from
    # replacing the stack restart already fixed and tested in CiderDarling.
    fixes = runtime_metadata.get("source_fixes", [])
    if isinstance(fixes, list) and "workqueue_stack_reset_x86_64" in fixes:
        return ["MACOBLOX_NATIVE_WORKQUEUE=1"]
    return []
