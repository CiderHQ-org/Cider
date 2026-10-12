"""Select one Darling executable, its matching root and its own guest prefix."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from .paths import user_directory

VARIANTS = ("regular", "ciderdarling")
SELECTION_KEYS = ("runtime", "executable", "sysroot", "prefix")


def _validate_selection(data):
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("runtime") not in VARIANTS):
        raise ValueError("unknown runtime or schema")
    for key in ("executable", "sysroot", "prefix"):
        value = data.get(key)
        if (not isinstance(value, str) or not Path(value).is_absolute()
                or any(character in value for character in "\n\r\0")):
            raise ValueError(f"invalid {key}")
    return data


def selection_path():
    return user_directory("CONFIG") / "runtime.json"


def remembered_runtimes(selection):
    result = {}
    if selection is None:
        return result
    history = selection.get("runtimes", {})
    if isinstance(history, dict):
        for variant in VARIANTS:
            try:
                entry = _validate_selection(history.get(variant))
                if entry["runtime"] == variant:
                    result[variant] = {key: entry[key] for key in SELECTION_KEYS}
            except ValueError:
                pass
    result[selection["runtime"]] = {key: selection[key] for key in SELECTION_KEYS}
    return result


def read_selection(path):
    """An explicit selection must never silently fall back to another runtime."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 16384:
            raise ValueError("file is too large")
        data = json.loads(path.read_text())
        return _validate_selection(data)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read Darling selection {path}: {error}. Rerun Cider's installer.") from error


def save_selection(selection, path=None, current=None):
    """Atomically select a runtime and remember both runtimes' custom paths."""
    data = {key: selection[key] for key in SELECTION_KEYS}
    data["schema_version"] = 1
    _validate_selection(data)
    path = Path(path) if path is not None else selection_path()
    history = remembered_runtimes(read_selection(path))
    if current is not None:
        snapshot = {key: current[key] for key in SELECTION_KEYS}
        snapshot["schema_version"] = 1
        try:
            _validate_selection(snapshot)
            history[current["runtime"]] = {key: current[key] for key in SELECTION_KEYS}
        except ValueError:
            pass  # The initial fallback may only have a missing client on PATH.
    history[data["runtime"]] = {key: data[key] for key in SELECTION_KEYS}
    data["runtimes"] = {variant: dict(entry, schema_version=1) for variant, entry in history.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".runtime-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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


def installed_runtimes(current=None, environment=None, selection_file=None,
                       regular_clients=None, cider_directory=Path("/opt/ciderdarling")):
    """Find usable installed clients; do not start Darling or install anything."""
    env = os.environ if environment is None else environment
    if env.get("FLATPAK_ID"):
        return {}
    saved = read_selection(selection_file if selection_file is not None else selection_path())
    remembered = remembered_runtimes(saved)
    if current is not None:
        remembered[current["runtime"]] = {key: current[key] for key in SELECTION_KEYS}
    found = {}

    def consider(executable, preferred=None, expected_variant=None):
        client = Path(executable)
        try:
            if not client.is_file() or not os.access(client, os.X_OK):
                return
            root = client.resolve().parent.parent / "libexec/darling"
            if not root.is_dir():
                return
            data = metadata(root)
            if data:
                if data.get("architecture") != "x86_64":
                    return
                variant = "ciderdarling"
            elif ((root / "usr/share/ciderdarling/runtime.json").exists()
                  or (root / "usr/share/ciderdarling/runtime.json").is_symlink()
                  or root.resolve().is_relative_to(Path(cider_directory).resolve())):
                return  # Damaged CiderDarling metadata is not regular Darling.
            else:
                variant = "regular"
            if expected_variant is not None and variant != expected_variant:
                return
            if variant in found:
                return
            previous = remembered.get(variant, {})
            default = Path.home() / (".ciderdarling" if variant == "ciderdarling" else ".darling")
            prefix = env.get("DPREFIX") or previous.get("prefix") or str(default)
            # A remembered custom tuple must agree with the actual client's
            # root. Keep its original path when the two resolve to the same root.
            if preferred is not None:
                if preferred["runtime"] != variant or Path(preferred["sysroot"]).resolve() != root.resolve():
                    return
                root = Path(preferred["sysroot"])
            entry = {"schema_version": 1, "runtime": variant, "executable": str(client.absolute()),
                     "sysroot": str(root), "prefix": str(Path(prefix).absolute())}
            found[variant] = _validate_selection(entry)
        except (OSError, ValueError):
            return

    for entry in remembered.values():
        consider(entry["executable"], entry)
    if regular_clients is None:
        regular_clients = [Path(directory) / "darling" for directory in
                           env.get("PATH", os.defpath).split(os.pathsep) if directory]
        regular_clients += [Path("/usr/local/bin/darling"), Path("/usr/bin/darling")]
    for client in regular_clients:
        consider(client)
    try:
        directories = sorted((path for path in Path(cider_directory).iterdir() if path.is_dir()),
                             key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        directories = []
    for directory in directories:
        consider(directory / "bin/darling", expected_variant="ciderdarling")
    return found


def resolve_runtime(environment=None, selection_file=None):
    env = os.environ if environment is None else environment
    # A Flatpak carries its own client, sysroot and rootless helper. Host
    # installer preferences cannot select files outside its sandbox.
    flatpak = bool(env.get("FLATPAK_ID"))
    selected = None if flatpak else read_selection(
        selection_file if selection_file is not None else selection_path())
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
    if selected is None and not flatpak and result["metadata"]:
        result["runtime"] = "ciderdarling"
    return result


def guest_variables(runtime_metadata):
    # This existing shim switch prevents the binary-scanning trampoline from
    # replacing the stack restart already fixed and tested in CiderDarling.
    fixes = runtime_metadata.get("source_fixes", [])
    if isinstance(fixes, list) and "workqueue_stack_reset_x86_64" in fixes:
        return ["MACOBLOX_NATIVE_WORKQUEUE=1"]
    return []
