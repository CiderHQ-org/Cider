"""Find the desktop's terminal emulator and the arguments that make it run a
command. GIO only knows a fixed list of terminals (older GLib not even kitty,
Alacritty, foot or WezTerm) and fails with "Unable to find terminal required
for application" otherwise; it remains the caller's last resort."""
import os
import shlex
import shutil

# Arguments placed between the terminal and the command. Only terminals that
# take the command as separate arguments are listed: tilix, lxterminal and
# qterminal expect one quoted string (GIO handles tilix itself).
EXEC_ARGUMENTS = {
    "xdg-terminal-exec": ["--"],
    "x-terminal-emulator": ["-e"],  # Debian policy: -e command [arguments]
    "ptyxis": ["--"],
    "kgx": ["--"],
    "gnome-terminal": ["--"],
    "konsole": ["-e"],
    "xfce4-terminal": ["-x"],
    "mate-terminal": ["-x"],
    "terminator": ["-x"],
    "kitty": [],  # the first non-option argument starts the command
    "alacritty": ["-e"],
    "foot": ["--"],
    "ghostty": ["-e"],
    "wezterm": ["start", "--"],
    "rio": ["-e"],
    "st": ["-e"],
    "urxvt": ["-e"],
    "xterm": ["-e"],
}

# The desktop's own terminal first when several are installed.
DESKTOP_TERMINALS = {
    "gnome": ("ptyxis", "kgx", "gnome-terminal"),
    "kde": ("konsole",),
    "xfce": ("xfce4-terminal",),
    "mate": ("mate-terminal",),
    "x-cinnamon": ("gnome-terminal",),
    "cinnamon": ("gnome-terminal",),
}


def command(argv, environ=None, which=None):
    """The full command line that runs argv in a new terminal window, or None
    when no known terminal is installed."""
    environ = os.environ if environ is None else environ
    which = which or shutil.which
    terminal = which("xdg-terminal-exec")
    if terminal:
        return [terminal, *EXEC_ARGUMENTS["xdg-terminal-exec"], *argv]
    # $TERMINAL may carry its own options ("kitty -1"); an unknown terminal
    # most likely understands -e.
    try:
        preferred = shlex.split(environ.get("TERMINAL", ""))
    except ValueError:
        preferred = []
    if preferred:
        terminal = which(preferred[0])
        if terminal:
            name = os.path.basename(terminal)
            return [terminal, *preferred[1:], *EXEC_ARGUMENTS.get(name, ["-e"]), *argv]
    desktops = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    names = [name for desktop in desktops for name in DESKTOP_TERMINALS.get(desktop, ())]
    names.append("x-terminal-emulator")
    names.extend(EXEC_ARGUMENTS)
    for name in dict.fromkeys(names):
        terminal = which(name)
        if terminal:
            return [terminal, *EXEC_ARGUMENTS[name], *argv]
    return None
