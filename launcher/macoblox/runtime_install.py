"""Monitor an interactive runtime installer independently of its terminal client."""
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from .runtime import VARIANTS


# All paths and the variant are positional arguments, never inserted into code.
# Some terminal applications exit their launch client before the shell finishes;
# the started/result files report the installer itself rather than that client.
# The installer records its build log's path in build-log (see install.sh).
TERMINAL_SCRIPT = r'''set -u
[[ -d "$3" ]] || exit 125
printf '%s\n' "$$" > "$3/started.tmp" && mv -- "$3/started.tmp" "$3/started" || exit 125
if CIDER_RUNTIME_LOG_RECORD="$3/build-log" bash "$1" --install-runtime --darling "$2"; then
    cider_install_status=0
else
    cider_install_status=$?
fi
printf '%s\n' "$cider_install_status" > "$3/result.tmp" && mv -- "$3/result.tmp" "$3/result" || exit 125
printf '\nCider runtime installer exited with status %s.\n' "$cider_install_status"
printf 'Press Enter to close this terminal. '
IFS= read -r || true
exit "$cider_install_status"
'''


class Installation:
    def __init__(self, installer, variant, directory):
        self.directory = Path(directory)
        self.created = time.monotonic()
        self.command = ["bash", "-c", TERMINAL_SCRIPT, "cider-runtime-install",
                        str(installer), variant, str(self.directory)]

    @classmethod
    def create(cls, project, variant, cache):
        if os.environ.get("FLATPAK_ID"):
            raise RuntimeError("Flatpak uses its bundled Darling runtime.")
        if variant not in VARIANTS:
            raise ValueError("Unknown Darling runtime")
        installer = Path(project).resolve() / "install.sh"
        if not installer.is_file():
            raise FileNotFoundError("Cider's installer is missing. Update or reinstall Cider first.")
        folder = Path(cache) / "installer"
        folder.mkdir(parents=True, exist_ok=True)
        directory = tempfile.mkdtemp(prefix="runtime-", dir=folder)
        return cls(installer, variant, directory)

    def poll(self):
        """None while running, otherwise its exit code; detect closed terminals."""
        try:
            result = (self.directory / "result").read_text()
        except FileNotFoundError:
            result = None
        if result is not None:
            if not result.strip().isdigit() or not 0 <= int(result) <= 255:
                raise RuntimeError("The runtime installer returned an invalid status.")
            return int(result)
        try:
            value = (self.directory / "started").read_text().strip()
        except FileNotFoundError:
            if time.monotonic() - self.created > 30:
                raise RuntimeError("The installation terminal did not start. Check that a terminal application is installed.")
            return None
        if not value.isdigit() or not 0 < int(value) < 2**31:
            raise RuntimeError("The installation terminal returned an invalid process ID.")
        try:
            arguments = Path(f"/proc/{int(value)}/cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            arguments = []
        if os.fsencode(self.directory) not in arguments:
            raise RuntimeError("The installation terminal closed before the installer finished.")
        return None

    def log_tail(self, lines=40):
        """The end of the installer's build log, or "" when there is none.

        Only a regular file in the installer cache folder is read: the path
        comes from a file the installer wrote.
        """
        try:
            path = Path((self.directory / "build-log").read_text().strip())
            if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                    or path.resolve().parent != self.directory.parent.resolve()):
                return ""
            with path.open("rb") as log:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - 65536))
                text = log.read().decode(errors="replace")
        except (OSError, ValueError):
            return ""
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\r", "\n")
        return "\n".join(line for line in text.splitlines()[-lines:])

    def close(self):
        # Only the temporary directory created for this job is removed.
        shutil.rmtree(self.directory)
