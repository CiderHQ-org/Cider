#!/usr/bin/env bash
# Quadra installer: Darling, the tools the launcher needs, and the
# launcher itself with its app menu entry. Run it again to update, or to
# uninstall.
#
#   curl -fsSL https://quadrahq.org/install.sh | bash
#
# In a terminal it guides setup; without one it installs. The choices
# also work as options (with curl: ... | bash -s -- --uninstall), see --help.
#
# Everything runs inside main(), called on the last line, so a download cut
# off halfway does nothing. The exit on that same line matters: main points
# stdin at the terminal (curl | bash), and bash would then read and run
# whatever is typed there as the rest of the script.

set -euo pipefail

REPO=https://github.com/QuadraHQ/Quadra.git
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
DIR=$DATA_HOME/QuadraHQ
LEGACY_CIDER_DIR=$DATA_HOME/CiderHQ
LEGACY_DIR=$DATA_HOME/MacOBlox
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
CACHE_HOME=${XDG_CACHE_HOME:-$HOME/.cache}
PREFIX=${DPREFIX:-$HOME/.darling}
# Darling's Debian packages, pinned to the release the Flatpak uses
# (flatpak/org.quadrahq.Quadra.yml; change both together). The checksum makes
# sure the download is that release, and a new Darling release cannot break
# installs before the shim was tested with it.
DARLING_TAG=v0.1.20260608
DARLING_DEBS_SHA256=27469ef3932da2e91dd7fb34b70e3628a3e54b7af9fb5480051f44af35eca1fd
CIDER_DARLING_REPO=https://github.com/QuadraHQ/CiderDarling.git
# Offline/source fallback. The launcher reads these literal assignments;
# complete CI releases are discovered through the stable update feed below.
CIDER_DARLING_REVISION=a8dae5f8e6daf6ec0245f94a9ba97c0d0cc4aeb7
CIDER_DARLING_MANIFEST=009cf8db2cfc409ceaafb602dac3ee0744e987396eb544e1361bc86910e03e44
CIDER_DARLING_INSTALL=/opt/ciderdarling/$CIDER_DARLING_REVISION
# SHA-256 of the pinned revision's prebuilt archives (CiderDarling's CI release
# bin-<12 hex digits>), by distribution family; empty: build from source.
# packaging/pin-ciderdarling.py sets these lines with the two above.
CIDER_DARLING_PREBUILT_ARCH=''
CIDER_DARLING_PREBUILT_UBUNTU2404=''
CIDER_DARLING_RELEASES=https://github.com/QuadraHQ/CiderDarling/releases/download
CIDER_DARLING_UPDATE_URL=$CIDER_DARLING_RELEASES/runtime-updates/stable.json
CIDER_DARLING_RELEASE_FILE=''
CIDER_DARLING_PINNED=''
CIDER_DARLING_RELEASE_RESOLVED=''
CIDER_DARLING_PREBUILT_ARCH_MANIFEST=''
CIDER_DARLING_PREBUILT_UBUNTU2404_MANIFEST=''
CIDER_DARLING_FROM_SOURCE=${CIDER_DARLING_FROM_SOURCE:-}
DARLING_RUNTIME=''
DARLING_CHOICE_EXPLICIT=''
DARLING_EXECUTABLE=''
DARLING_SELECTION=()

# Colours unless NO_COLOR is set or the output is no terminal; arrows and
# dots only where the locale is UTF-8.
if [[ -t 1 && -z ${NO_COLOR:-} && ${TERM:-dumb} != dumb ]]; then
  BOLD=$'\033[1m' DIM=$'\033[2m' RESET=$'\033[0m' ACCENT=$'\033[1;35m'
  GOOD=$'\033[1;32m' BAD=$'\033[1;31m' SELECTED=$'\033[1;97;45m'
  SHADES=($'\033[38;5;213m' $'\033[38;5;177m' $'\033[38;5;141m' $'\033[38;5;105m')
else
  BOLD='' DIM='' RESET='' ACCENT='' GOOD='' BAD='' SELECTED=''
  SHADES=('' '' '' '')
fi
case ${LC_ALL:-${LC_CTYPE:-${LANG:-}}} in
  *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*)
    POINTER='❯' BULLET='•' ON='●' OFF='○' KEYS='↑/↓ move · enter choose · q quit' ;;
  *) POINTER='>' BULLET='-' ON='*' OFF='-' KEYS='up/down move, enter choose, q quit' ;;
esac

say() { printf '  %s%s%s %s\n' "$ACCENT" "$BULLET" "$RESET" "$*"; }
die() { printf '%sError:%s %s\n' "$BAD" "$RESET" "$*" >&2; exit 1; }

darling_runtime_name() {
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    printf '%s' "QuadraHQ's CiderDarling"
  else
    printf '%s' 'Regular Darling'
  fi
}

migrate_user_directories() {
  local base target source old
  for base in "$CONFIG_HOME" "$CACHE_HOME" "$DATA_HOME"; do
    target=$base/quadrahq
    if [[ -e $target || -L $target ]]; then
      # Keep existing Quadra data; an empty directory may be replaced.
      [[ -d $target ]] && rmdir -- "$target" 2>/dev/null || continue
    fi
    for old in ciderhq macoblox; do
      source=$base/$old
      [[ -d $source ]] || continue
      mv -T --no-clobber -- "$source" "$target"
      [[ ! -e $source ]] || die "Could not migrate $source to $target; no files were replaced."
      break
    done
  done
}

load_darling_selection() {
  migrate_user_directories
  local saved='' file=$CONFIG_HOME/quadrahq/runtime.json
  if [[ -f $file ]]; then
    command -v python3 >/dev/null || die "Python 3 is needed to read the saved Darling selection."
    saved=$(python3 - "$file" "$DARLING_RUNTIME" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
try:
    if path.stat().st_size > 16384: raise ValueError('file is too large')
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('runtime') not in ('regular', 'ciderdarling'):
        raise ValueError('unknown runtime or schema')
    for key in ('executable', 'sysroot', 'prefix'):
        value = data.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or any(c in value for c in '\n\r\0'):
            raise ValueError(f'invalid {key}')
    history = data.get('runtimes', {})
    entry = history.get(sys.argv[2]) if isinstance(history, dict) else None
    if isinstance(entry, dict) and entry.get('schema_version') == 1 and entry.get('runtime') == sys.argv[2]:
        for key in ('executable', 'sysroot', 'prefix'):
            value = entry.get(key)
            if not isinstance(value, str) or not Path(value).is_absolute() or any(c in value for c in '\n\r\0'):
                raise ValueError(f'invalid remembered {key}')
        data = entry
    print('\n'.join(data[key] for key in ('runtime', 'executable', 'sysroot', 'prefix')))
except (OSError, ValueError) as error:
    sys.exit(f'Cannot read {path}: {error}')
PY
    ) || die "Cannot read the saved Darling selection. Fix $file before continuing."
    mapfile -t DARLING_SELECTION <<< "$saved"
  fi
  DARLING_RUNTIME=${DARLING_RUNTIME:-${DARLING_SELECTION[0]:-regular}}
  case $DARLING_RUNTIME in
    regular | ciderdarling) ;;
    *) die "--darling must be regular or ciderdarling." ;;
  esac
  select_darling_prefix
  if [[ ${DARLING_SELECTION[0]:-} == "$DARLING_RUNTIME" ]]; then
    DARLING_EXECUTABLE=${DARLING_SELECTION[1]}
  elif [[ $DARLING_RUNTIME == ciderdarling ]]; then
    DARLING_EXECUTABLE=$CIDER_DARLING_INSTALL/bin/darling
  else
    DARLING_EXECUTABLE=$(command -v darling || printf '%s' darling)
  fi
}

select_darling_prefix() {
  if [[ -n ${DPREFIX:-} ]]; then
    PREFIX=$DPREFIX
  elif [[ ${DARLING_SELECTION[0]:-} == "$DARLING_RUNTIME" ]]; then
    PREFIX=${DARLING_SELECTION[3]}
  elif [[ $DARLING_RUNTIME == ciderdarling ]]; then
    PREFIX=$HOME/.ciderdarling
  else
    PREFIX=$HOME/.darling
  fi
}

save_darling_selection() {
  migrate_user_directories
  # Activate only after the launcher and its selected-root shim built
  # successfully. A failed build leaves the previous selection available.
  # With "remember" (a runtime-only install), only an update of the active
  # variant changes the selection; another variant is just remembered, and
  # nothing is written before a first selection exists.
  python3 - "${1:-activate}" "$CONFIG_HOME/quadrahq/runtime.json" "$DARLING_RUNTIME" "$DARLING_EXECUTABLE" "$DARLING_SYSROOT" "$PREFIX" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile
mode = sys.argv[1]
path = Path(sys.argv[2])
data = dict(zip(('runtime', 'executable', 'sysroot', 'prefix'), sys.argv[3:]))
data['schema_version'] = 1
for key in ('executable', 'sysroot', 'prefix'):
    data[key] = str(Path(data[key]).absolute())
history = {}
active = None
previous = None
if mode == 'remember' and not path.exists():
    sys.exit(0)
if path.exists():
    if path.stat().st_size > 16384: raise ValueError('saved runtime file is too large')
    old = json.loads(path.read_text())
    previous = old.get('previous_ciderdarling') if isinstance(old, dict) else None
    entries = old.get('runtimes', {}) if isinstance(old, dict) else {}
    candidates = [*entries.values(), old] if isinstance(entries, dict) else [old]
    for entry in candidates:
        if not isinstance(entry, dict) or entry.get('schema_version') != 1 or entry.get('runtime') not in ('regular', 'ciderdarling'):
            continue
        if all(isinstance(entry.get(key), str) and Path(entry[key]).is_absolute() and not any(c in entry[key] for c in '\n\r\0')
               for key in ('executable', 'sysroot', 'prefix')):
            history[entry['runtime']] = {key: entry[key] for key in ('schema_version', 'runtime', 'executable', 'sysroot', 'prefix')}
            if entry is old:
                active = dict(history[entry['runtime']])
old_cider = history.get('ciderdarling')
if data['runtime'] == 'ciderdarling' and old_cider and old_cider['sysroot'] != data['sysroot']:
    previous = dict(old_cider)
history[data['runtime']] = dict(data)
if mode == 'remember' and active is not None and active['runtime'] != data['runtime']:
    data = active
data['runtimes'] = history
if (isinstance(previous, dict) and previous.get('schema_version') == 1
        and previous.get('runtime') == 'ciderdarling'
        and all(isinstance(previous.get(key), str) and Path(previous[key]).is_absolute()
                and not any(c in previous[key] for c in '\n\r\0')
                for key in ('executable', 'sysroot', 'prefix'))):
    data['previous_ciderdarling'] = {key: previous[key] for key in ('schema_version', 'runtime', 'executable', 'sysroot', 'prefix')}
path.parent.mkdir(parents=True, exist_ok=True)
temporary = None
try:
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.runtime-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    if temporary is not None: temporary.unlink(missing_ok=True)
PY
}

select_regular_darling() {
  local executable root
  while IFS= read -r executable; do
    [[ -x $executable ]] || continue
    root=$(dirname -- "$(dirname -- "$(readlink -f -- "$executable")")")/libexec/darling
    [[ -d $root && ! -f $root/usr/share/ciderdarling/runtime.json ]] || continue
    DARLING_EXECUTABLE=$executable
    export DARLING_SYSROOT=$root
    return 0
  done < <(
    if [[ ${DARLING_SELECTION[0]:-} == regular ]]; then printf '%s\n' "${DARLING_SELECTION[1]}"; fi
    type -aP darling || true
  )
  return 1
}

ciderdarling_matches() {
  [[ -x $CIDER_DARLING_INSTALL/bin/darling ]] || return 1
  python3 - "$CIDER_DARLING_INSTALL/libexec/darling/usr/share/ciderdarling/runtime.json" "$CIDER_DARLING_REVISION" "$CIDER_DARLING_MANIFEST" <<'PY'
import json
from pathlib import Path
import sys
try:
    data = json.loads(Path(sys.argv[1]).read_text())
    valid = (data.get('schema_version') == 1 and data.get('name') == 'CiderDarling'
             and data.get('architecture') == 'x86_64' and data.get('source_revision') == sys.argv[2]
             and data.get('patch_manifest_sha256') == sys.argv[3])
except (OSError, ValueError, AttributeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

UPDATE_BACKUP=''
INSTALL_LOG=''
# NEW: Track whether we're showing live output
SHOW_BUILD_OUTPUT=${SHOW_BUILD_OUTPUT:-1}

step() { printf '\n%s[%s/4] %s%s\n' "$BOLD" "$1" "$2" "$RESET"; }

distribution_name() {
  local PRETTY_NAME='' ID='' ID_LIKE=''
  [[ ! -r /etc/os-release ]] || . /etc/os-release
  printf '%s' "${PRETTY_NAME:-${NAME:-Linux}}"
}

# IMPROVED: More robust distro detection with fallback
detect_package_manager() {
  local ID='' ID_LIKE='' VERSION_ID='' family manager
  [[ ! -r /etc/os-release ]] || . /etc/os-release
  family=" ${ID:-} ${ID_LIKE:-} "

  # Check immutable/special systems first
  if [[ -e /run/ostree-booted ]]; then
    printf '%s' manual; return
  elif [[ -e /etc/NIXOS ]]; then
    printf '%s' manual; return
  elif [[ -e /etc/transactional-update.conf ]]; then
    printf '%s' manual; return
  elif [[ -f /etc/os-release ]] && grep -q "^ID.*=.*\(nixos\|guix\|steamos\|microos\|aeon\|kalpa\)" /etc/os-release; then
    printf '%s' manual; return
  fi

  # Try ID first, then ID_LIKE
  case "$ID" in
    arch|archarm) printf '%s' pacman; return ;;
    debian|ubuntu|devuan|pop) printf '%s' apt-get; return ;;
    fedora|rhel|centos|alma|rocky) printf '%s' dnf; return ;;
    opensuse*|suse) printf '%s' zypper; return ;;
    alpine) printf '%s' apk; return ;;
    gentoo|gentoo-prefix) printf '%s' emerge; return ;;
    void) printf '%s' xbps-install; return ;;
    solus) printf '%s' eopkg; return ;;
  esac

  # Try ID_LIKE patterns as fallback
  if [[ "$family" == *" arch "* ]]; then
    printf '%s' pacman; return
  elif [[ "$family" == *" debian "* ]] || [[ "$family" == *" ubuntu "* ]]; then
    printf '%s' apt-get; return
  elif [[ "$family" == *" fedora "* ]] || [[ "$family" == *" rhel "* ]] || [[ "$family" == *" centos "* ]]; then
    printf '%s' dnf; return
  elif [[ "$family" == *" suse "* ]] || [[ "$family" == *" opensuse "* ]]; then
    printf '%s' zypper; return
  elif [[ "$family" == *" alpine "* ]]; then
    printf '%s' apk; return
  fi

  # Fall back to checking which manager exists on PATH
  for manager in pacman apt-get dnf zypper apk xbps-install eopkg emerge yum; do
    if command -v "$manager" >/dev/null 2>&1; then
      printf '%s' "$manager"; return
    fi
  done

  printf '%s' manual
}

setup_plan() {
  local operation='Install' dependencies='your package manager'
  is_installed && operation='Update'
  dependencies=$(detect_package_manager)
  [[ $dependencies != pacman ]] || dependencies='pacman and the AUR'
  printf '  %sSetup plan%s\n\n' "$BOLD" "$RESET"
  printf '    1. Prepare Darling and the system tools (%s).\n' "$dependencies"
  printf '    2. %s the Quadra launcher.\n' "$operation"
  printf '    3. Build its compatibility libraries.\n'
  printf '    4. Add the app menu entry and quadrahq command.\n\n'
  printf '  Computer    %s (%s)\n' "$(distribution_name)" "$(uname -m)"
  printf '  Destination %s\n' "${DIR/#$HOME/\~}"
  printf '  Runtime     %s\n' "$(darling_runtime_name)"
  printf '  Prefix      %s\n' "${PREFIX/#$HOME/\~}"
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    printf '  %sCiderDarling builds from source into its own versioned directory.%s\n' "$DIM" "$RESET"
    printf '  %sIts separate prefix needs sign-in on first use; regular Darling data stays available.%s\n' "$DIM" "$RESET"
  fi
  printf '  %sSystem packages may ask for your sudo password.%s\n' "$DIM" "$RESET"
  if is_installed; then
    printf '  %sUpdates keep settings, Roblox, Studio and existing backups.%s\n' "$DIM" "$RESET"
    printf '  %sLocal source changes are backed up before replacement.%s\n' "$DIM" "$RESET"
  else
    printf '  %sFirst launch guides Roblox installation and sign-in.%s\n' "$DIM" "$RESET"
  fi
}

# Keep recovery material outside the checkout. A reset can remove untracked
# files that obstruct incoming tracked paths; back those up too, and leave
# other untracked/ignored files in place instead of using git clean.
backup_checkout_changes() {
  local list_dir relative backup
  list_dir=$(mktemp -d)
  git -C "$DIR" diff --name-only -z HEAD > "$list_dir/tracked"
  git -C "$DIR" ls-files --others --exclude-standard -z > "$list_dir/untracked"
  if [[ ! -s $list_dir/tracked && ! -s $list_dir/untracked ]]; then
    rm -rf -- "$list_dir"
    return
  fi
  backup=$(umask 077; mkdir -p -- "$DATA_HOME/QuadraHQ-backups";
    mktemp -d "$DATA_HOME/QuadraHQ-backups/update-$(date -u +%Y%m%d-%H%M%S)-XXXXXX")
  git -C "$DIR" rev-parse HEAD > "$backup/revision"
  git -C "$DIR" diff --binary HEAD > "$backup/tracked.patch"
  cp -- "$list_dir/tracked" "$backup/tracked-paths"
  cp -- "$list_dir/untracked" "$backup/untracked-paths"
  while IFS= read -r -d '' relative; do
    [[ -e $DIR/$relative || -L $DIR/$relative ]] || continue
    mkdir -p -- "$backup/files/$(dirname -- "$relative")"
    cp -a -- "$DIR/$relative" "$backup/files/$relative"
  done < <(cat -- "$list_dir/tracked" "$list_dir/untracked")
  rm -rf -- "$list_dir"
  UPDATE_BACKUP=$backup
  say "Local changes saved to ${backup/#$HOME/\~}"
}

# The website lives on main for hosting, but is not part of an app install.
# Partial fetches omit blobs until checkout requests them; sparse checkout
# keeps hosting paths from requesting those blobs or entering the worktree.
configure_launcher_checkout() {
  git -C "$DIR" config remote.origin.promisor true
  git -C "$DIR" config remote.origin.partialclonefilter blob:none
  git -C "$DIR" sparse-checkout set --no-cone --stdin <<'PATTERNS'
/*
!/website/
!/.github/
!/vercel.json
!/.vercel/
!/.vercelignore
PATTERNS
}

setup_success() {
  local version
  version=$(installed_version)
  printf '\n%s%s Setup complete%s\n' "$GOOD" "$ON" "$RESET"
  printf '  Quadra%s is ready in your app menu.\n' "${version:+ $version}"
  printf '\n  %sNext steps%s\n' "$BOLD" "$RESET"
  printf '    1. Open Quadra from the app menu, or run quadrahq.\n'
  if [[ -d $DIR/RobloxPlayer.app ]]; then
    printf '    2. Launch Roblox from the launcher.\n'
    printf '    3. Sign in if needed, then choose a game.\n'
  else
    printf '    2. Follow its welcome screen to install Roblox.\n'
    printf '    3. Sign in to Roblox and choose a game.\n'
  fi
  [[ -z $UPDATE_BACKUP ]] || printf '\n  Source backup: %s\n' "${UPDATE_BACKUP/#$HOME/\~}"
  [[ -z $INSTALL_LOG ]] || printf '  Build log: %s\n' "${INSTALL_LOG/#$HOME/\~}"
  printf '\n'
}

# ------------------------------------------------------------------ install

install_arch() {
  # Only packages that are not installed at all: asking pacman for an
  # installed but outdated one (pipewire-audio 1.6.8 with 1.6.9 in the repo)
  # makes it a partial upgrade that breaks on pinned dependencies.
  local wanted=(git curl base-devel clang lld unzip python python-gobject gtk4 libadwaita webkitgtk-6.0 sdl2-compat wayland pkgconf)
  command -v pw-cat >/dev/null || wanted+=(pipewire-audio)
  local missing
  missing=$(pacman -T "${wanted[@]}" || true)
  if [[ -n $missing ]]; then
    say "Installing tools (pacman): $(echo $missing)"
    # shellcheck disable=SC2086
    sudo pacman -S --needed --noconfirm $missing ||
      die "pacman could not install them. Update the system with 'sudo pacman -Syu' and run this again."
  fi
}

install_debian() {
  say "Installing tools (apt)"
  sudo apt-get update
  sudo apt-get install -y git curl unzip clang lld pipewire-bin python3 python3-gi \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 libsdl2-dev libwayland-dev pkg-config
}

install_fedora() {
  say "Installing tools (dnf)"
  sudo dnf install -y git curl clang lld unzip pipewire-utils python3 python3-gobject gtk4 libadwaita webkitgtk6.0 SDL2-devel wayland-devel pkgconf-pkg-config
}

# Launcher dependencies; Darling is handled centrally after validation.
install_opensuse() {
  say "Installing tools (zypper)"
  sudo zypper --non-interactive install git curl unzip clang lld pipewire-tools \
    python3 python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 \
    typelib-1_0-WebKit-6_0 libSDL2-devel wayland-devel pkg-config
}

install_alpine() {
  say "Installing tools (apk); Darling needs an Alpine-specific source build"
  sudo apk add git curl unzip clang lld pipewire-tools python3 py3-gobject3 \
    gtk4.0 libadwaita webkit2gtk-6.0 sdl2-dev wayland-dev pkgconf
}

install_gentoo() {
  say "Installing tools (emerge); enable introspection and GTK 4 WebKit support in Portage"
  sudo emerge --noreplace dev-vcs/git net-misc/curl app-arch/unzip \
    llvm-core/clang llvm-core/lld media-video/pipewire dev-lang/python \
    dev-python/pygobject gui-libs/gtk:4 gui-libs/libadwaita \
    net-libs/webkit-gtk:6 media-libs/libsdl2 dev-libs/wayland dev-util/pkgconf
}

install_void() {
  say "Installing tools (xbps-install)"
  sudo xbps-install -Sy git curl unzip clang lld pipewire python3 python3-gobject \
    gtk4 libadwaita libwebkitgtk60 libwebkitgtk60-devel SDL2-devel wayland-devel pkg-config
}

install_solus() {
  say "Installing tools (eopkg)"
  sudo eopkg install -y git curl unzip clang lld pipewire python3 python-gobject \
    gtk4 libadwaita webkit-gtk sdl2-devel wayland-devel pkg-config
}

install_tools() {
  case $(detect_package_manager) in
    pacman) install_arch ;;
    apt-get) install_debian ;;
    dnf) install_fedora ;;
    yum)
      say "Installing tools (yum); older enterprise releases may lack GTK 4/WebKit 6"
      sudo yum install -y git curl clang lld unzip pipewire-utils python3 python3-gobject \
        gtk4 libadwaita webkitgtk6.0 SDL2-devel wayland-devel pkgconf-pkg-config ;;
    zypper) install_opensuse ;;
    apk) install_alpine ;;
    emerge) install_gentoo ;;
    xbps-install) install_void ;;
    eopkg) install_solus ;;
    manual)
      say "Manual dependencies required on this host (including immutable Linux, NixOS and Guix)."
      say "Install Darling, git, clang, lld, unzip, PipeWire, Python 3/PyGObject, GTK 4, libadwaita, WebKit 6, SDL2, Wayland and pkg-config using your host's supported method."
      ;;
  esac
}

# Only offer compilation after the configured repositories have been checked.
try_darling_package() {
  local manager=$1
  case $manager in
    pacman) pacman -Si darling >/dev/null 2>&1 || return 1
      sudo pacman -S --needed --noconfirm darling || return 1 ;;
    apt-get) apt-cache show darling >/dev/null 2>&1 || return 1
      sudo apt-get install -y darling || return 1 ;;
    dnf|yum) "$manager" list --available darling >/dev/null 2>&1 || return 1
      sudo "$manager" install -y darling || return 1 ;;
    zypper) zypper --non-interactive search --match-exact --type package darling 2>/dev/null | grep -q "darling" || return 1
      sudo zypper --non-interactive install darling || return 1 ;;
    apk) apk search -x darling 2>/dev/null | grep -q "^darling" || return 1
      sudo apk add darling || return 1 ;;
    xbps-install) xbps-query -R darling >/dev/null 2>&1 || return 1
      sudo xbps-install -y darling || return 1 ;;
    emerge) emerge --pretend --quiet app-emulation/darling >/dev/null 2>&1 || return 1
      # Portage packages may themselves compile: ask before invoking emerge.
      confirm_darling_build || die "Darling compilation declined. Setup stopped."
      sudo emerge --noreplace app-emulation/darling || return 1 ;;
    eopkg) eopkg info darling >/dev/null 2>&1 || return 1
      sudo eopkg install -y darling || return 1 ;;
    *) return 1 ;;
  esac
  hash -r
  command -v darling >/dev/null
}

confirm_darling_build() {
  local answer=''
  say "$(darling_runtime_name) needs compilation on $(distribution_name)."
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    say "This installs build dependencies and CiderDarling into $CIDER_DARLING_INSTALL using sudo."
    say "The build uses pinned CiderDarling ${CIDER_DARLING_REVISION:0:12}, 64-bit OpenGL and a saved log."
  else
    say "This installs build dependencies and Darling into /usr/local using sudo."
    say "The build uses the pinned $DARLING_TAG release, 64-bit components and a saved log."
  fi
  say "Allow several hours, at least 4 GiB RAM and about 25 GiB free disk space."
  # Never consume piped installer text, and --yes does not bypass this prompt.
  if ! (: </dev/tty) 2>/dev/null; then
    die "Source compilation requires confirmation in a terminal. Rerun interactively."
  fi
  printf '  Compile Darling and continue? [y/N] ' >/dev/tty
  IFS= read -r answer </dev/tty || return 1
  [[ $answer == [Yy] || $answer == [Yy][Ee][Ss] ]]
}

install_darling_build_dependencies() {
  case $1 in
    apt-get) sudo apt-get install -y build-essential cmake clang bison flex xz-utils git git-lfs python3 \
      libfuse-dev libudev-dev libcap2-bin libglu1-mesa-dev libcairo2-dev libgl-dev \
      libtiff-dev libfreetype-dev libxml2-dev libegl-dev libfontconfig-dev libbsd-dev \
      libxrandr-dev libxcursor-dev libgif-dev libpulse-dev libavformat-dev libavcodec-dev \
      libswresample-dev libdbus-1-dev libxkbfile-dev libssl-dev llvm-dev libelf-dev \
      libvulkan-dev libcurl4-openssl-dev libedit-dev ;;
    pacman)
      local -a graphics_packages=(mesa)
      if pacman -Qq mesa-git >/dev/null 2>&1; then
        say "Using the installed mesa-git in place of the conflicting mesa package."
        graphics_packages=()
      fi
      sudo pacman -S --needed --noconfirm make cmake clang flex bison icu fuse git python \
        pkgconf fontconfig cairo libtiff "${graphics_packages[@]}" glu llvm libbsd libxkbfile libxcursor \
        libxext libxkbcommon libxrandr ffmpeg git-lfs vulkan-headers vulkan-icd-loader ;;
    dnf|yum) sudo "$1" install -y make gcc gcc-c++ cmake clang bison flex git git-lfs python3 \
      dbus-devel glibc-devel fuse-devel systemd-devel elfutils-libelf-devel cairo-devel \
      freetype-devel libjpeg-turbo-devel fontconfig-devel libglvnd-devel mesa-libGL-devel \
      mesa-libEGL-devel mesa-libGLU-devel libtiff-devel libxml2-devel libbsd-devel \
      libXcursor-devel libXrandr-devel giflib-devel pulseaudio-libs-devel libxkbfile-devel \
      openssl-devel llvm-devel libcap-devel libavcodec-free-devel libavformat-free-devel ;;
    zypper) sudo zypper --non-interactive install make gcc gcc-c++ cmake clang bison flex \
      git git-lfs python3 fuse-devel systemd-devel libelf-devel cairo-devel freetype2-devel \
      fontconfig-devel Mesa-libGL-devel Mesa-libEGL-devel glu-devel libxml2-devel \
      libbsd-devel libXcursor-devel libXrandr-devel giflib-devel libpulse-devel \
      libxkbfile-devel libopenssl-devel llvm-devel libcap-devel libtiff-devel \
      libjpeg-devel dbus-1-devel libavcodec-devel libavformat-devel libswresample-devel ;;
    apk) sudo apk add build-base cmake clang bison flex xz fuse-dev libcap-dev git git-lfs \
      python3 glu-dev cairo-dev mesa-dev tiff-dev freetype-dev libxml2-dev fontconfig-dev \
      libbsd-dev libxrandr-dev libxcursor-dev giflib-dev pulseaudio-dev ffmpeg-dev \
      dbus-dev libxkbfile-dev openssl-dev linux-headers llvm-dev xdg-user-dirs ;;
    xbps-install) sudo xbps-install -y base-devel cmake clang bison flex xz git git-lfs python3 \
      fuse-devel libcap-devel eudev-libudev-devel glu-devel cairo-devel MesaLib-devel \
      tiff-devel freetype-devel libxml2-devel fontconfig-devel libbsd-devel \
      libXrandr-devel libXcursor-devel giflib-devel pulseaudio-devel ffmpeg-devel \
      dbus-devel libxkbfile-devel openssl-devel llvm21-devel ;;
    emerge) sudo emerge --noreplace dev-build/cmake llvm-core/clang llvm-core/llvm \
      sys-devel/bison sys-devel/flex dev-vcs/git dev-vcs/git-lfs dev-lang/python sys-fs/fuse:0 sys-libs/libcap \
      virtual/libudev media-libs/glu x11-libs/cairo media-libs/mesa media-libs/tiff \
      media-libs/freetype dev-libs/libxml2 media-libs/fontconfig dev-libs/libbsd \
      x11-libs/libXrandr x11-libs/libXcursor media-libs/giflib media-libs/libpulse \
      media-video/ffmpeg sys-apps/dbus x11-libs/libxkbfile dev-libs/openssl ;;
    eopkg) sudo eopkg install -y -c system.devel || return 1
      sudo eopkg install -y cmake clang llvm-devel bison flex git git-lfs python3 fuse-devel \
        libcap-devel systemd-devel mesalib-devel cairo-devel libtiff-devel freetype2-devel \
        libxml2-devel fontconfig-devel libbsd-devel libxrandr-devel libxcursor-devel \
        giflib-devel pulseaudio-devel ffmpeg-devel dbus-devel libxkbfile-devel openssl-devel ;;
    *) die "Automatic source installation is unavailable on this host; use https://docs.darlinghq.org/build-instructions.html with your host's supported installation method." ;;
  esac
}

# Clang 23 can emit Objective-C constant classes absent from Darling's
# Foundation. Query each compiler instead of passing new flags to older Clang.
darling_literal_flags() {
  local compiler=$1 help family
  help=$("$compiler" -cc1 -help) || return 1
  for family in nsnumber nsarray nsdictionary; do
    if [[ $help == *"-fconstant-$family-literals"* ]]; then
      printf '%s ' "-fno-constant-$family-literals"
    fi
  done
}

prepare_darling_compiler_compatibility() {
  # These edits describe the pinned v0.1.20260608 submodules. Validate every
  # original fragment before writing, and recognize already applied edits.
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
patches = {
    'src/external/cfnetwork/src/HTTP/NSHTTPCookieStorage.m': [
        ('return @[];', 'return [NSArray array];', 1),
    ],
    'src/external/iokitd/src/IORegistryEntry.mm': [
        ('return @{};', 'return [NSDictionary dictionary];', 1),
    ],
    'src/external/security/OSX/sec/Security/SecKeyProxy.m': [
        ('reply(result ? @[result] : @[], error)',
         'reply(result ? @[result] : [NSArray array], error)', 1),
        ('NSMutableArray *parameters = @[].mutableCopy;',
         'NSMutableArray *parameters = [NSMutableArray array];', 1),
    ],
    'src/external/security/trust/trustd/SecPinningDb.m': [
        ('kSecPinningDbKeyRules:@[@{}]',
         'kSecPinningDbKeyRules:@[[NSDictionary dictionary]]', 2),
    ],
    'src/external/security/keychain/SecureObjectSync/SOSControlServer.m': [
        ('complete(@[], [NSError errorWithDomain:',
         'complete([NSArray array], [NSError errorWithDomain:', 1),
    ],
    'src/external/security/OSX/sec/ipc/server_endpoint.m': [
        ('fakeEntitlements: @{}]', 'fakeEntitlements: [NSDictionary dictionary]]', 1),
    ],
}

branch_include = '''#include <llvm-c/BitReader.h>
#include <llvm/Config/llvm-config.h>

// LLVM 23 split the C API's branch opcode; keep older LLVM builds supported.
#if LLVM_VERSION_MAJOR >= 23
#define CIDER_LLVM_CONDITIONAL_BRANCH LLVMCondBr
#define CIDER_LLVM_UNCONDITIONAL_BRANCH LLVMUncondBr
#else
#define CIDER_LLVM_CONDITIONAL_BRANCH LLVMBr
#define CIDER_LLVM_UNCONDITIONAL_BRANCH LLVMBr
#endif'''
patches['src/external/metal/deps/indium/src/iridium/air.cpp'] = [
    ('#include <llvm-c/BitReader.h>', branch_include, 1),
    ('lastInstOpcode == LLVMBr &&', 'lastInstOpcode == CIDER_LLVM_CONDITIONAL_BRANCH &&', 1),
    ('lastInstOpcodeFirstBlock == LLVMBr &&',
     'lastInstOpcodeFirstBlock == CIDER_LLVM_UNCONDITIONAL_BRANCH &&', 1),
    ('lastInstOpcodeSecondBlock == LLVMBr &&',
     'lastInstOpcodeSecondBlock == CIDER_LLVM_UNCONDITIONAL_BRANCH &&', 1),
    ('case LLVMBr: {', '''#if LLVM_VERSION_MAJOR >= 23
                case LLVMUncondBr:
                case LLVMCondBr: {
#else
                case LLVMBr: {
#endif''', 1),
]

prepared = []
for relative, edits in patches.items():
    path = root / relative
    original = path.read_text()
    text = original
    for before, after, count in edits:
        # Some replacements contain the original fragment (includes/cases).
        after_count = text.count(after)
        before_count = text.count(before)
        if after_count == count and before_count == count * after.count(before):
            continue
        if before_count != count or after_count:
            raise SystemExit(f'Darling compiler compatibility: unexpected source layout in {relative}; no files changed')
        text = text.replace(before, after)
    if text != original:
        prepared.append((path, text))
for path, text in prepared:
    path.write_text(text)
print(f'Darling compiler compatibility: prepared {len(prepared)} source files (LLVM 23 branches are version guarded)')
PY
}

darling_build_jobs() {
  local requested=${DARLING_BUILD_JOBS:-auto}
  if [[ $requested != auto ]]; then
    [[ $requested =~ ^[1-9][0-9]*$ && ${#requested} -le 4 ]] && ((requested <= 8192)) ||
      die "DARLING_BUILD_JOBS must be auto or an integer between 1 and 8192."
    printf '%s' "$requested"
    return
  fi
  python3 - <<'PY'
import math
import os
from pathlib import Path
cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
memory = None
try:
    fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    memory = int(fields.get('MemAvailable', fields['MemTotal']).split()[0]) * 1024
except (OSError, ValueError, KeyError):
    pass
# Walk v2 ancestors: a nested scope may inherit a tighter CPU or RAM limit.
try:
    relative = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    mount = Path('/sys/fs/cgroup')
    current = mount / relative.lstrip('/')
    while current.is_relative_to(mount):
        try:
            quota, period = (current / 'cpu.max').read_text().split()
            if quota != 'max': cpus = min(cpus, max(1, math.ceil(int(quota) / int(period))))
        except (OSError, ValueError, ZeroDivisionError):
            pass
        try:
            limit = (current / 'memory.max').read_text().strip()
            used = int((current / 'memory.current').read_text())
            if limit != 'max':
                headroom = max(0, int(limit) - used)
                memory = headroom if memory is None else min(memory, headroom)
        except (OSError, ValueError):
            pass
        if current == mount: break
        current = current.parent
except (OSError, StopIteration):
    pass
# Reserve 25% headroom, budget 1 GiB per compiler. Low-memory hosts can use
# DARLING_BUILD_JOBS=1 and swap; an explicit override wins over this policy.
jobs = min(cpus, int(memory * .75) // (1024**3)) if memory is not None else min(cpus, 2)
print(max(1, min(jobs, 8192)))
PY
}

download_ciderdarling() (
  local source=$1 jobs=$2
  export GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false GIT_LFS_SKIP_SMUDGE=1
  local -a public_git=(git -c credential.helper= -c core.askPass=/bin/false
    -c filter.lfs.required=false -c filter.lfs.smudge= -c filter.lfs.process=)
  "${public_git[@]}" clone --no-checkout --depth 1 "$CIDER_DARLING_REPO" "$source" || return 1
  "${public_git[@]}" -C "$source" fetch --depth 1 origin "$CIDER_DARLING_REVISION" || return 1
  "${public_git[@]}" -C "$source" checkout --detach FETCH_HEAD || return 1
  [[ $(git -C "$source" rev-parse HEAD) == "$CIDER_DARLING_REVISION" ]] || return 1
  # Dependency fetches have their own bounded parallelism; compilation uses
  # the full memory-aware job count below.
  ((jobs <= 32)) || jobs=32
  python3 "$source/tools/cider/bootstrap.py" --jobs "$jobs"
)

build_darling_source() {
  local manager=$1 build log jobs install_prefix=/usr/local
  local -a runtime_options=()
  jobs=$(darling_build_jobs) || die "Cannot determine the Darling build job count."
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    install_prefix=$CIDER_DARLING_INSTALL
    runtime_options=(-DENABLE_METAL=OFF -DCIDER_APPLY_PATCHES=ON -DCIDER_SHUTDOWN_ON_INSTALL=OFF -DCMAKE_BUILD_TYPE=RelWithDebInfo)
  fi
  install_darling_build_dependencies "$manager" || die "Could not install Darling build dependencies. Check enabled repositories and package names for your distro, then rerun."
  mkdir -p -- "$CACHE_HOME/quadrahq/installer"
  # Every build starts from a fresh tree, so earlier ones (kept by older
  # installers, or left by a failed build) only take disk space: several GB.
  local old_build
  for old_build in "$CACHE_HOME/quadrahq/installer"/darling-source-*; do
    [[ -d $old_build && ! -L $old_build ]] || continue
    say "Removing earlier build files: ${old_build/#$HOME/\~}"
    rm -rf -- "$old_build" || say "Could not remove all of $old_build; continuing."
  done
  build=$(umask 077; mktemp -d "$CACHE_HOME/quadrahq/installer/darling-source-XXXXXX")
  # The log lives next to the tree, which is removed after a successful install.
  log=$(umask 077; mktemp "$CACHE_HOME/quadrahq/installer/darling-build-$(date -u +%Y%m%d-%H%M%S)-XXXXXX.log")
  # The launcher's runtime installer shows the end of this log on failure.
  [[ -z ${CIDER_RUNTIME_LOG_RECORD:-} ]] || printf '%s\n' "$log" > "$CIDER_RUNTIME_LOG_RECORD" || true
  say "Building $(darling_runtime_name); sources: $build"
  say "Build log: $log"

  # Public source does not need credentials. Swift's optional SDK binaries
  # use a separate LFS service; Roblox uses the C/C++/Objective-C runtime.
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    download_ciderdarling "$build/source" "$jobs" 2>&1 | tee "$log" ||
      die "Pinned CiderDarling source preparation failed. Log: $log"
  else
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false \
      GIT_LFS_SKIP_SMUDGE=1 GIT_CLONE_PROTECTION_ACTIVE=false \
      git -c credential.helper= -c core.askPass=/bin/false clone --recursive --branch "$DARLING_TAG" \
      https://github.com/darlinghq/darling.git "$build/source" 2>&1 | tee "$log" ||
      die "Public Darling source download failed; no GitHub login is needed. Check the failed repository URL in: $log"

    git -C "$build/source" lfs install --local --skip-smudge 2>&1 | tee -a "$log" ||
      die "Git LFS initialization failed. Log: $log"
    local swift_library first_line
    for swift_library in "$build/source/src/external/swift"/*.dylib; do
      [[ -f $swift_library ]] || continue
      first_line=''
      IFS= read -r -n 80 first_line < "$swift_library" || true
      if [[ $first_line == 'version https://git-lfs.github.com/spec/v1' ]]; then
        rm -- "$swift_library"
      fi
    done
    say "Optional Swift SDK LFS downloads skipped; Roblox's runtime is built from source."

    prepare_darling_compiler_compatibility "$build/source" 2>&1 | tee -a "$log" ||
      die "Darling compiler compatibility preparation failed. Log: $log"
  fi
  local c_literal_flags cxx_literal_flags
  c_literal_flags=$(darling_literal_flags clang) || die "Cannot inspect Clang's supported Objective-C flags."
  cxx_literal_flags=$(darling_literal_flags clang++) || die "Cannot inspect Clang++'s supported Objective-C flags."
  [[ -z $c_literal_flags$cxx_literal_flags ]] || say "Disabling Objective-C constant literals unsupported by Darling's Foundation."

  # Configure with live output
  say "Configuring Darling (this may take a few minutes)..."
  cmake -S "$build/source" -B "$build/build" -DTARGET_i386=OFF \
    -DCMAKE_C_FLAGS="${CFLAGS:-} $c_literal_flags" \
    -DCMAKE_CXX_FLAGS="${CXXFLAGS:-} $cxx_literal_flags" \
    -DCMAKE_INSTALL_PREFIX="$install_prefix" "${runtime_options[@]}" 2>&1 | tee -a "$log" ||
    die "Darling configuration failed; check distro build dependencies. Log: $log"

  # Build with live output
  say "Compiling Darling (using $jobs parallel jobs; this will take a while)..."
  cmake --build "$build/build" --parallel "$jobs" 2>&1 | tee -a "$log" ||
    die "Darling compilation failed. Log: $log"

  # Install with live output
  say "Installing Darling..."
  sudo cmake --install "$build/build" 2>&1 | tee -a "$log" || die "Darling installation failed. Log: $log"

  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    ciderdarling_matches || die "Installed CiderDarling metadata does not match the pinned source. Log: $log"
  else
    export PATH="/usr/local/bin:$PATH"
  fi
  hash -r
  [[ -x $install_prefix/bin/darling ]] || die "Build completed but darling was not installed. Log: $log"
  rm -rf -- "$build" || say "Could not remove all build files in $build."
  say "Darling installed. Build files removed; log kept at $log"
}

# Retain the existing checksum-verified upstream Debian binary option.
try_darling_debs() {
  local build
  build=$(mktemp -d)
  say "Trying Darling $DARLING_TAG upstream Debian packages"
  if ! curl -fL --progress-bar -o "$build/debs.zip" \
    "https://github.com/darlinghq/darling/releases/download/$DARLING_TAG/debs_${DARLING_TAG##*.}.zip"; then
    rm -rf -- "$build"; return 1
  fi
  if ! printf '%s  %s\n' "$DARLING_DEBS_SHA256" "$build/debs.zip" | sha256sum -c --quiet -; then
    rm -rf -- "$build"
    die "The Darling download does not match its checksum. Setup stopped."
  fi
  if ! unzip -q "$build/debs.zip" -d "$build"; then rm -rf -- "$build"; return 1; fi
  if ! sudo apt-get install -y "$build"/debs_*/*.deb; then rm -rf -- "$build"; return 1; fi
  rm -rf -- "$build"
  hash -r
  command -v darling >/dev/null
}

resolve_ciderdarling_release() {
  [[ -z $CIDER_DARLING_RELEASE_RESOLVED ]] || return 0
  CIDER_DARLING_RELEASE_RESOLVED=1
  local file=$CIDER_DARLING_RELEASE_FILE downloaded='' pins=''
  local -a values=()
  if [[ -z $file ]]; then
    [[ -z $CIDER_DARLING_PINNED ]] || return 0
    mkdir -p -- "$CACHE_HOME/quadrahq/installer"
    downloaded=$(umask 077; mktemp "$CACHE_HOME/quadrahq/installer/.release-XXXXXX")
    if command -v curl >/dev/null && curl -fsSL --connect-timeout 4 --max-time 12 \
      "$CIDER_DARLING_UPDATE_URL" -o "$downloaded"; then
      file=$downloaded
    else
      rm -f -- "$downloaded"
      file=$CACHE_HOME/quadrahq/runtime-release.json
      [[ -f $file ]] || { say "Runtime update service unavailable; using Quadra's bundled runtime pin."; return 0; }
    fi
  fi
  if ! pins=$(python3 - "$file" <<'PY'
import json, os, re, sys
def require(condition):
    if not condition:
        raise ValueError("invalid release field")
try:
    if os.path.getsize(sys.argv[1]) > 65536:
        raise ValueError('file too large')
    data = json.load(open(sys.argv[1]))
    revision, series = data['source_revision'], data['patch_manifest_sha256']
    require(data['schema_version'] == 1 and data['name'] == 'CiderDarling')
    require(data['architecture'] == 'x86_64' and data['channel'] == 'stable')
    require(re.fullmatch('[0-9a-f]{40}', revision) and re.fullmatch('[0-9a-f]{64}', series))
    # The feed's CI still names the repository by its previous owner.
    require(data['release_url'] in [f'https://github.com/{owner}/releases/tag/bin-{revision[:12]}'
                                    for owner in ('QuadraHQ/CiderDarling', 'CiderHQ-org/CiderDarling')])
    require(type(data['source_date']) is int and data['source_date'] > 0)
    minimum = data['minimum_cider']
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', minimum))
    require(tuple(map(int, minimum.split('.'))) <= (0, 23))
    require(isinstance(data['supersedes'], list) and len(data['supersedes']) <= 128)
    require(all(re.fullmatch('[0-9a-f]{40}', value) for value in data['supersedes']))
    output = [revision, series]
    for flavor in ('arch', 'ubuntu24.04'):
        build = data['builds'][flavor]
        stem = f'ciderdarling-{revision}-x86_64-{flavor}'
        require(build['archive'] == stem + '.tar.xz' and build['manifest'] == stem + '.json')
        require(type(build['archive_bytes']) is int and 0 < build['archive_bytes'] < 20 * 1024**3)
        for field in ('min_glibc', 'min_glibcxx', 'min_cxxabi', 'min_libgcc'):
            require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', build[field]))
        require(isinstance(build['native_libraries'], list) and len(build['native_libraries']) <= 256)
        require(all(re.fullmatch(r'lib[A-Za-z0-9_+.-]+\.so(?:\.[0-9]+)*', value) for value in build['native_libraries']))
        for field in ('archive_sha256', 'manifest_sha256'):
            require(re.fullmatch('[0-9a-f]{64}', build[field]))
            output.append(build[field])
    print('\n'.join(output))
except (OSError, ValueError, KeyError, TypeError, AssertionError):
    sys.exit(1)
PY
  ); then
    [[ -z $downloaded ]] || rm -f -- "$downloaded"
    [[ -z $CIDER_DARLING_RELEASE_FILE ]] || die "Invalid or incompatible CiderDarling release metadata."
    say "No compatible runtime update metadata; using Quadra's bundled runtime pin."
    return 0
  fi
  mapfile -t values <<< "$pins"
  CIDER_DARLING_REVISION=${values[0]}
  CIDER_DARLING_MANIFEST=${values[1]}
  CIDER_DARLING_PREBUILT_ARCH=${values[2]}
  CIDER_DARLING_PREBUILT_ARCH_MANIFEST=${values[3]}
  CIDER_DARLING_PREBUILT_UBUNTU2404=${values[4]}
  CIDER_DARLING_PREBUILT_UBUNTU2404_MANIFEST=${values[5]}
  CIDER_DARLING_INSTALL=/opt/ciderdarling/$CIDER_DARLING_REVISION
  [[ -z $downloaded ]] || rm -f -- "$downloaded"
  say "Using published CiderDarling ${CIDER_DARLING_REVISION:0:12}."
}

# Prebuilt CiderDarling. Darling's bridges to host libraries name the build
# host's exact library versions, so an archive suits one distribution family:
# arch, or ubuntu24.04 (Debian family with glibc 2.39 or newer). Prints the
# family, or nothing.
ciderdarling_prebuilt_flavor() {
  local ID='' ID_LIKE='' glibc='' release=${CIDER_OS_RELEASE:-/etc/os-release}
  [[ ! -r $release ]] || . "$release"
  if command -v pacman >/dev/null && [[ " $ID $ID_LIKE " == *" arch "* ]]; then
    printf arch
  elif command -v apt-get >/dev/null && [[ " $ID $ID_LIKE " == *" ubuntu "* || " $ID $ID_LIKE " == *" debian "* ]]; then
    glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)
    glibc=${glibc##* }
    [[ -n $glibc ]] && printf '%s\n2.39\n' "$glibc" | sort -CV -r && printf ubuntu24.04
  fi
  return 0
}

ciderdarling_prebuilt_sha256() {
  case $1 in
    arch) printf '%s' "$CIDER_DARLING_PREBUILT_ARCH" ;;
    ubuntu24.04) printf '%s' "$CIDER_DARLING_PREBUILT_UBUNTU2404" ;;
  esac
}

# The host libraries a prebuilt build loads, by package manager. A failure
# (packages of another release) leaves the source build.
install_ciderdarling_libraries() {
  case $1 in
    pacman) sudo pacman -S --needed --noconfirm cairo dbus ffmpeg fontconfig freetype2 fuse2 giflib \
      libjpeg-turbo libpng libpulse libtiff libx11 libxcursor libxext libxkbfile libxrandr libglvnd \
      vulkan-icd-loader ;;
    apt-get) sudo apt-get install -y --no-install-recommends libcairo2 libdbus-1-3 libfontconfig1 \
      libfreetype6 libfuse2t64 libgif7 libjpeg-turbo8 libpng16-16t64 libpulse0 libtiff6 libx11-6 \
      libxcursor1 libxext6 libxkbfile1 libxrandr2 libegl1 libgl1 libvulkan1 libavcodec60 libavformat60 \
      libavutil58 libswresample4 ;;
    *) return 1 ;;
  esac
}

# Libraries the manifest's build needs that this host lacks. FFmpeg's are
# left out: the launcher repairs those bridges for other FFmpeg versions.
ciderdarling_missing_libraries() {
  python3 - "$1" <<'PY'
import json
import shutil
import subprocess
import sys
manifest = json.load(open(sys.argv[1]))
ldconfig = shutil.which("ldconfig") or "/sbin/ldconfig"
listing = subprocess.run([ldconfig, "-p"], capture_output=True, text=True).stdout.splitlines()[1:]
present = {line.split()[0] for line in listing if line.split() and "x86-64" in line}
needed = manifest.get("shared_libraries", []) + manifest.get("native_libraries", [])
ffmpeg = ("libavcodec.", "libavformat.", "libavutil.", "libswresample.")
print(" ".join(name for name in needed if name not in present and not name.startswith(ffmpeg)))
PY
}

# The manifest describes the pinned revision's archive with the pinned
# checksum, for a glibc this host has.
ciderdarling_manifest_matches() {
  python3 - "$1" "$2" "$3" "$CIDER_DARLING_REVISION" "$CIDER_DARLING_MANIFEST" <<'PY'
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
path, archive, digest, revision, series = sys.argv[1:]
try:
    data = json.load(open(path))
    glibc = os.confstr("CS_GNU_LIBC_VERSION").split()[-1]
    key = lambda text: tuple(int(part) for part in text.split("."))
    valid = (data.get("schema_version") == 1 and data.get("name") == "CiderDarling"
             and data.get("source_revision") == revision and data.get("patch_manifest_sha256") == series
             and data.get("archive") == archive and data.get("archive_sha256") == digest
             and data.get("install_prefix") == f"/opt/ciderdarling/{revision}"
             and key(data.get("min_glibc", "0")) <= key(glibc))
    # Match the host's actual symbol generations before unpacking a runtime.
    # libstdc++ can be too old even on a host with a sufficient glibc.
    listing = subprocess.run([shutil.which('ldconfig') or '/sbin/ldconfig', '-p'],
                             capture_output=True, text=True, timeout=5).stdout
    for soname, families in [('libstdc++.so.6', ('GLIBCXX', 'CXXABI')), ('libgcc_s.so.1', ('GCC',))]:
        library = next((line.split('=>', 1)[1].strip() for line in listing.splitlines()
                        if soname in line and 'x86-64' in line and '=>' in line), None)
        if library and Path(library).stat().st_size <= 32 * 1024**2:
            content = Path(library).read_bytes()
        else:
            content = b''
        fields = {'GLIBCXX': 'min_glibcxx', 'CXXABI': 'min_cxxabi', 'GCC': 'min_libgcc'}
        for family in families:
            needed = data.get(fields[family], '0')
            versions = re.findall(rb'(?<![A-Z])' + family.encode() + rb'_([0-9]+(?:\.[0-9]+)+)', content)
            available = max((key(value.decode()) for value in versions), default=(0,))
            valid = valid and key(needed) <= available
except (OSError, ValueError, AttributeError, TypeError, IndexError, subprocess.SubprocessError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

# Ownership survives only an unpack by root: bin/darling must stay setuid root.
ciderdarling_client_is_setuid_root() {
  [[ $(stat -c '%u %a' -- "$1" 2>/dev/null) == '0 4755' ]]
}

download_ciderdarling_archive() {
  local output=$1 name=$2 url=$3 digest=$4 folder part
  folder=$CACHE_HOME/quadrahq/installer/downloads
  mkdir -p -- "$folder"
  chmod 700 -- "$folder"
  part=$folder/$name.tar.xz.part
  # Serialize only downloads of this exact immutable release. The partial
  # file survives terminal closure and never contains guest/account data.
  (
    flock -n 9 || { say "This runtime download is already running in another terminal."; exit 1; }
    [[ ! -L $part && ( ! -e $part || -f $part ) ]] || exit 1
    if [[ -s $part ]] && printf '%s  %s\n' "$digest" "$part" | sha256sum -c --quiet - 2>/dev/null; then
      cp -- "$part" "$output"
      exit
    fi
    if ! curl -fL --progress-bar --retry 3 --retry-delay 2 --connect-timeout 15 \
        --continue-at - -o "$part" "$url"; then
      say "Download interrupted. Rerun to resume the saved partial download."
      exit 1
    fi
    if ! printf '%s  %s\n' "$digest" "$part" | sha256sum -c --quiet -; then
      rm -f -- "$part"
      say "The CiderDarling download does not match its pinned checksum; the invalid cached download was removed."
      exit 1
    fi
    cp -- "$part" "$output"
  ) 9> "$folder/$name.lock"
}

# Install the pinned revision's prebuilt archive into CIDER_DARLING_INSTALL.
# Returns 1 (to build from source instead) when there is none for this host.
try_ciderdarling_prebuilt() {
  local manager=$1 flavor digest manifest_digest name url work missing staging unpacked
  if [[ -n $CIDER_DARLING_FROM_SOURCE ]]; then
    say "Building CiderDarling from source as requested."
    return 1
  fi
  flavor=$(ciderdarling_prebuilt_flavor)
  digest=$(ciderdarling_prebuilt_sha256 "$flavor")
  case $flavor in
    arch) manifest_digest=$CIDER_DARLING_PREBUILT_ARCH_MANIFEST ;;
    ubuntu24.04) manifest_digest=$CIDER_DARLING_PREBUILT_UBUNTU2404_MANIFEST ;;
    *) manifest_digest='' ;;
  esac
  if [[ -z $flavor || -z $digest ]]; then
    say "No prebuilt CiderDarling ${CIDER_DARLING_REVISION:0:12} for $(distribution_name); building from source."
    return 1
  fi
  name=ciderdarling-$CIDER_DARLING_REVISION-x86_64-$flavor
  url=$CIDER_DARLING_RELEASES/bin-${CIDER_DARLING_REVISION:0:12}
  mkdir -p -- "$CACHE_HOME/quadrahq/installer"
  work=$(umask 077; mktemp -d "$CACHE_HOME/quadrahq/installer/prebuilt-XXXXXX")
  say "Downloading prebuilt CiderDarling ${CIDER_DARLING_REVISION:0:12} ($flavor)"
  if ! curl -fsSL --retry 3 --connect-timeout 15 -o "$work/$name.json" "$url/$name.json"; then
    rm -rf -- "$work"
    say "The prebuilt download is unavailable; building from source."
    return 1
  fi
  if ! download_ciderdarling_archive "$work/$name.tar.xz" "$name" "$url/$name.tar.xz" "$digest"; then
    rm -rf -- "$work"
    die "The runtime download did not finish. Rerun to resume it, or use --from-source to compile. Your selected runtime is unchanged."
  fi
  if ! printf '%s  %s\n' "$digest" "$work/$name.tar.xz" | sha256sum -c --quiet -; then
    rm -rf -- "$work"
    die "The prebuilt CiderDarling download does not match its pinned checksum. Setup stopped."
  fi
  if [[ -n $manifest_digest ]] && ! printf '%s  %s\n' "$manifest_digest" "$work/$name.json" | sha256sum -c --quiet -; then
    rm -rf -- "$work"
    die "The CiderDarling manifest does not match the published checksum. Setup stopped."
  fi
  if ! ciderdarling_manifest_matches "$work/$name.json" "$name.tar.xz" "$digest"; then
    rm -rf -- "$work"
    say "The prebuilt build does not suit this system (revision, patch series or glibc); building from source."
    return 1
  fi
  say "Installing the libraries CiderDarling uses"
  install_ciderdarling_libraries "$manager" || say "Some libraries could not be installed; checking what is present."
  missing=$(ciderdarling_missing_libraries "$work/$name.json")
  if [[ -n $missing ]]; then
    rm -rf -- "$work"
    say "This system lacks libraries the prebuilt build was made with ($missing); building from source."
    return 1
  fi
  staging=${CIDER_DARLING_INSTALL%/*}/.partial-$CIDER_DARLING_REVISION
  unpacked=$staging/$CIDER_DARLING_REVISION
  say "Installing CiderDarling into $CIDER_DARLING_INSTALL"
  sudo rm -rf -- "$staging" && sudo mkdir -p -- "$staging" &&
    sudo tar -xpJf "$work/$name.tar.xz" --numeric-owner --same-owner -C "$staging" ||
    { sudo rm -rf -- "$staging"; rm -rf -- "$work"; die "Could not unpack CiderDarling into ${staging%/*}."; }
  rm -rf -- "$work"
  if ! ciderdarling_client_is_setuid_root "$unpacked/bin/darling" ||
     ! CIDER_DARLING_INSTALL=$unpacked ciderdarling_matches; then
    sudo rm -rf -- "$staging"
    die "The unpacked CiderDarling is incomplete or not setuid root. Setup stopped."
  fi
  sudo mv --no-target-directory -- "$unpacked" "$CIDER_DARLING_INSTALL" ||
    { sudo rm -rf -- "$staging"; die "Could not move CiderDarling into $CIDER_DARLING_INSTALL."; }
  sudo rm -rf -- "$staging"
  # File capabilities are not in the archive; `cmake --install` sets this one.
  sudo setcap cap_sys_admin=ep "$CIDER_DARLING_INSTALL/libexec/darling/usr/sbin/fseventsd" 2>/dev/null ||
    say "Could not set fseventsd's capability (file change notifications may be limited)."
  hash -r
  say "Installed prebuilt CiderDarling ${CIDER_DARLING_REVISION:0:12}."
}

# An interrupted sudo install leaves the pinned version directory without
# matching metadata. Only that exact directory is removed, after asking (or
# with --replace-incomplete-runtime when there is no terminal to ask in).
REPLACE_INCOMPLETE_RUNTIME=''
remove_incomplete_ciderdarling() {
  local answer='' target=$CIDER_DARLING_INSTALL
  say "CiderDarling's version directory exists with incomplete or mismatched metadata:"
  say "  $target"
  say "This usually means an earlier installation was interrupted."
  [[ $CIDER_DARLING_REVISION =~ ^[0-9a-f]{40}$ && ${target##*/} == "$CIDER_DARLING_REVISION" &&
     -d $target && ! -L $target ]] ||
    die "$target is not a CiderDarling version directory, so it is left alone. Move it aside and rerun."
  if [[ -z $REPLACE_INCOMPLETE_RUNTIME ]]; then
    if ! (: </dev/tty) 2>/dev/null; then
      die "Not removing $target without a terminal to ask in. Rerun interactively, or add --replace-incomplete-runtime."
    fi
    printf '  Remove it with sudo and install CiderDarling again? [y/N] ' >/dev/tty
    IFS= read -r answer </dev/tty || answer=''
    [[ $answer == [Yy] || $answer == [Yy][Ee][Ss] ]] ||
      die "Kept $target. Remove it with: sudo rm -rf -- '$target' (or rerun with --replace-incomplete-runtime)."
  fi
  say "Removing the incomplete CiderDarling installation"
  sudo rm -rf -- "$target" || die "Could not remove $target."
  [[ ! -e $target && ! -L $target ]] || die "$target is still present after removal."
}

ensure_darling() {
  local manager
  if [[ $DARLING_RUNTIME == ciderdarling ]]; then
    resolve_ciderdarling_release
    if ! ciderdarling_matches; then
      if [[ -e $CIDER_DARLING_INSTALL || -L $CIDER_DARLING_INSTALL ]]; then
        remove_incomplete_ciderdarling
      fi
      manager=$(detect_package_manager)
      if ! try_ciderdarling_prebuilt "$manager"; then
        [[ $manager != manual ]] || die "CiderDarling source installation needs your host's supported build method on this system."
        confirm_darling_build || die "CiderDarling compilation declined. Setup stopped."
        build_darling_source "$manager"
      fi
    fi
    DARLING_EXECUTABLE=$CIDER_DARLING_INSTALL/bin/darling
    export DARLING_SYSROOT=$CIDER_DARLING_INSTALL/libexec/darling
    export DPREFIX=$PREFIX
    return
  fi
  select_regular_darling && { export DPREFIX=$PREFIX; return 0; }
  manager=$(detect_package_manager)
  [[ $manager != manual ]] || die "Install Darling using your immutable/NixOS/Guix host's supported method."
  say "Checking configured repositories for Darling"
  if try_darling_package "$manager" && select_regular_darling; then export DPREFIX=$PREFIX; return 0; fi
  if [[ $manager == apt-get ]] && try_darling_debs && select_regular_darling; then export DPREFIX=$PREFIX; return 0; fi
  say "No usable Darling package was installed from the configured repositories."
  confirm_darling_build || die "Darling compilation declined. Setup stopped."
  build_darling_source "$manager"
  select_regular_darling || die "Regular Darling was built but its matching client and runtime root are unavailable."
  export DPREFIX=$PREFIX
}

validate_tools() {
  local tool
  for tool in git clang ld.lld unzip python3 pw-cat pkg-config; do
    command -v "$tool" >/dev/null || {
      if [[ $tool == darling ]]; then
        die "Darling is not installed. Follow https://docs.darlinghq.org/build-instructions.html for your distro (Alpine needs its specific instructions), then rerun this installer."
      fi
      die "$tool is missing. Install it using your distribution's supported method and rerun this installer."
    }
  done
  pkg-config --exists sdl2 wayland-client ||
    die "SDL2/Wayland development files are missing. Install their development packages and rerun."
  python3 - <<'PYTHON' || die "Python bindings for GTK 4, Adwaita 1 or WebKit 6 are missing. Check your distro packages/Portage USE flags and rerun."
import gi
for namespace, version in [('Gtk', '4.0'), ('Adw', '1'), ('WebKit', '6.0')]:
    gi.require_version(namespace, version)
from gi.repository import Gtk, Adw, WebKit
PYTHON
}

do_install_runtime() {
  [[ $(uname -m) == x86_64 ]] || die "Darling runs only on x86_64."
  command -v python3 >/dev/null || die "Python 3 is required for runtime installation."
  say "Installing $(darling_runtime_name) for use with Quadra."
  ensure_darling
  # Point the saved choice at this installation (a new CiderDarling revision
  # lives in a new directory); another active runtime stays selected.
  save_darling_selection remember
  say "$(darling_runtime_name) is installed. Return to Quadra and apply the runtime choice when ready."
}

# Moves a recognized earlier repository URL (the upstream MacOBlox repositories,
# or Cider's CiderHQ-org/Cider before the QuadraHQ organization) to $REPO.
# Other user-configured remotes are kept.
migrate_origin_remote() {
  case $(git -C "$DIR" remote get-url origin 2>/dev/null) in
    https://github.com/narezy/MacOBlox | https://github.com/narezy/MacOBlox.git | \
    https://github.com/aubree-lat/MacOBlox | https://github.com/aubree-lat/MacOBlox.git | \
    git@github.com:aubree-lat/MacOBlox | git@github.com:aubree-lat/MacOBlox.git | \
    ssh://git@github.com/aubree-lat/MacOBlox | ssh://git@github.com/aubree-lat/MacOBlox.git | \
    https://github.com/CiderHQ-org/Cider | https://github.com/CiderHQ-org/Cider.git | \
    git@github.com:CiderHQ-org/Cider | git@github.com:CiderHQ-org/Cider.git | \
    ssh://git@github.com/CiderHQ-org/Cider | ssh://git@github.com/CiderHQ-org/Cider.git)
      git -C "$DIR" remote set-url origin "$REPO" ;;
  esac
}

do_install() {
  [[ $(uname -m) == x86_64 ]] || die "Darling runs only on x86_64."
  local legacy=''
  if [[ ! -e $DIR ]] && legacy=$(existing_checkout); then
    say "Migrating the existing ${legacy##*/} checkout to QuadraHQ"
    mv -T --no-clobber -- "$legacy" "$DIR"
    [[ ! -e $legacy ]] || die "Quadra's destination appeared during migration; no files were replaced."
  fi
  [[ ! -e $DIR ]] || { [[ -d $DIR/.git ]] && launcher_package "$DIR" >/dev/null; } ||
    die "$DIR already exists without a Git checkout. Move it aside before installing."
  step 1 "Prepare the system tools"
  install_tools
  validate_tools
  ensure_darling

  step 2 "Prepare Quadra"
  if [[ -d $DIR/.git ]]; then
    say "Updating Quadra"

    migrate_origin_remote

    # Fetch first, then preserve local repairs before replacing tracked files.
    # Session data, downloads and backups stay in the checkout unchanged.
    git -C "$DIR" config remote.origin.promisor true
    git -C "$DIR" config remote.origin.partialclonefilter blob:none
    git -C "$DIR" fetch --filter=blob:none origin main
    backup_checkout_changes
    configure_launcher_checkout
    git -C "$DIR" reset --hard origin/main

  else
    say "Downloading Quadra"
    git clone --filter=blob:none --no-checkout --depth 1 --single-branch --branch main "$REPO" "$DIR"
    configure_launcher_checkout
    git -C "$DIR" reset --hard HEAD
  fi
  step 3 "Build the compatibility libraries"
  say "This can take a few minutes."
  mkdir -p -- "$CACHE_HOME/quadrahq/installer"
  INSTALL_LOG=$(umask 077; mktemp "$CACHE_HOME/quadrahq/installer/build-$(date -u +%Y%m%d-%H%M%S)-XXXXXX.log")

  # IMPROVED: Show build output live with tee
  if ! DARLING_SYSROOT="$DARLING_SYSROOT" "$DIR/build_debug_shim.sh" 2>&1 | tee "$INSTALL_LOG"; then
    say "Build output saved to: $INSTALL_LOG"
    say "Last 40 lines of output:"
    tail -n 40 -- "$INSTALL_LOG" >&2
    die "Build failed. See full log above or at: $INSTALL_LOG"
  fi
  say "Compatibility libraries built."
  step 4 "Add the launcher to your desktop"
  "$DIR/launcher/install.sh"
  save_darling_selection
  setup_success
}

# ---------------------------------------------------------------- uninstall

# The launcher's Python package in a checkout: launcher/quadra, or
# launcher/macoblox in a checkout from before the rename.
launcher_package() {
  local name
  for name in quadra macoblox; do
    if [[ -f $1/launcher/$name/core.py ]]; then
      printf '%s' "$1/launcher/$name"
      return 0
    fi
  done
  return 1
}

# The checkout this script makes: nothing is deleted unless $DIR is one.
existing_checkout() {
  local checkout
  for checkout in "$DIR" "$LEGACY_CIDER_DIR" "$LEGACY_DIR"; do
    if [[ -f $checkout/build_debug_shim.sh ]] && launcher_package "$checkout" >/dev/null &&
       [[ -f $checkout/launcher/quadrahq-launcher || -f $checkout/launcher/ciderhq-launcher ||
          -f $checkout/launcher/macoblox-launcher ]]; then
      printf '%s' "$checkout"
      return 0
    fi
  done
  return 1
}
is_installed() {
  existing_checkout >/dev/null
}
installed_version() {
  local checkout package
  checkout=$(existing_checkout) || return 0
  package=$(launcher_package "$checkout") || return 0
  sed -n 's/^__version__ = "\(.*\)"/\1/p' "$package/__init__.py" 2>/dev/null
}

# Removes what do_install and the launcher put on this computer; with an
# argument, Darling's prefix as well. Darling and the other packages stay.
do_uninstall() {
  local purge=${1:-}
  if [[ ! -e $DIR ]]; then
    DIR=$(existing_checkout) || DIR=$DATA_HOME/QuadraHQ
  fi
  if [[ -e $DIR ]] && ! [[ -f $DIR/build_debug_shim.sh &&
      ( -f $DIR/launcher/quadrahq-launcher || -f $DIR/launcher/ciderhq-launcher ||
        -f $DIR/launcher/macoblox-launcher ) ]]; then
    die "$DIR does not look like Quadra, so it is left alone."
  fi
  # Nothing in the prefix may change under a running Darling (it keeps
  # showing deleted files), and nothing should run from the folder that goes.
  if pgrep -u "$(id -u)" -x darlingserver >/dev/null 2>&1; then
    say "Stopping Roblox and Darling"
    DPREFIX="$PREFIX" "$DARLING_EXECUTABLE" shutdown >/dev/null 2>&1 || true
  fi
  if [[ -x $DIR/studio/wine/bin/wineserver ]]; then
    WINEPREFIX=$DIR/studio/prefix "$DIR/studio/wine/bin/wineserver" -k >/dev/null 2>&1 || true
  fi
  if [[ -e $DIR ]]; then
    say "Removing the launcher, Roblox and Studio (${DIR/#$HOME/\~})"
    rm -rf -- "$DIR"
  fi
  say "Removing the app menu entries, icons and the quadrahq command"
  local apps=$DATA_HOME/applications
  rm -f -- "$apps/org.quadrahq.Quadra.desktop" "$apps/org.quadrahq.Quadra.URI.desktop" \
    "$apps/org.quadrahq.Quadra.Studio.desktop" "$apps/quadrahq-roblox-window.desktop" \
    "$DATA_HOME"/icons/hicolor/*/apps/quadrahq.png \
    "$DATA_HOME/icons/hicolor/scalable/apps/quadrahq.svg" "$DATA_HOME/mime/packages/org.quadrahq.Quadra.xml"
  # Only Quadra's own CiderDarling entry; a user's entry of that name stays.
  local cider_entry=$apps/org.quadrahq.Quadra.CiderDarling.desktop
  if [[ -f $cider_entry && ! -L $cider_entry ]] && grep -qsx 'X-QuadraHQ-Managed=true' "$cider_entry"; then
    rm -f -- "$cider_entry"
  fi
  local cider_link=$HOME/.local/bin/quadrahq
  if [[ -L $cider_link && $(readlink "$cider_link") == */quadrahq-launcher ]]; then
    rm -f -- "$cider_link"
  fi
  rm -f -- "$apps/org.ciderhq.Cider.desktop" "$apps/org.ciderhq.Cider.URI.desktop" \
    "$apps/org.ciderhq.Cider.Studio.desktop" "$apps/ciderhq-roblox-window.desktop" \
    "$DATA_HOME"/icons/hicolor/*/apps/ciderhq.png \
    "$DATA_HOME/icons/hicolor/scalable/apps/ciderhq.svg" "$DATA_HOME/mime/packages/org.ciderhq.Cider.xml"
  local old_entry=$apps/org.ciderhq.Cider.CiderDarling.desktop old_link=$HOME/.local/bin/ciderhq
  if [[ -f $old_entry && ! -L $old_entry ]] && grep -qsx 'X-CiderHQ-Managed=true' "$old_entry"; then
    rm -f -- "$old_entry"
  fi
  if [[ -L $old_link && $(readlink "$old_link") == */ciderhq-launcher ]]; then
    rm -f -- "$old_link"
  fi
  # The xyz.narez.* names are the app ID before 0.15.
  rm -f -- "$apps/wtf.aubree.MacOBlox.desktop" "$apps/wtf.aubree.MacOBlox.URI.desktop" \
    "$apps/wtf.aubree.MacOBlox.Studio.desktop" \
    "$apps/xyz.narez.MacOBlox.desktop" "$apps/xyz.narez.MacOBlox.Studio.desktop" \
    "$apps/macoblox-roblox-window.desktop" "$apps/org.macoblox.Launcher.desktop" \
    "$DATA_HOME"/icons/hicolor/*/apps/macoblox.png "$DATA_HOME/mime/packages/wtf.aubree.MacOBlox.xml" \
    "$DATA_HOME/mime/packages/xyz.narez.MacOBlox.xml"
  local link=$HOME/.local/bin/macoblox
  if [[ -L $link && $(readlink "$link") == */macoblox-launcher ]]; then
    rm -f -- "$link"
  fi
  # Studio as the handler of roblox-studio: links and place files.
  if [[ -f $CONFIG_HOME/mimeapps.list ]]; then
    sed -i -e 's/org\.quadrahq\.Quadra\.Studio\.desktop;\{0,1\}//g' \
      -e 's/org\.quadrahq\.Quadra\.URI\.desktop;\{0,1\}//g' \
      -e 's/org\.ciderhq\.Cider\.Studio\.desktop;\{0,1\}//g' \
      -e 's/org\.ciderhq\.Cider\.URI\.desktop;\{0,1\}//g' \
      -e 's/wtf\.aubree\.MacOBlox\.Studio\.desktop;\{0,1\}//g' \
      -e 's/wtf\.aubree\.MacOBlox\.URI\.desktop;\{0,1\}//g' \
      -e 's/xyz\.narez\.MacOBlox\.Studio\.desktop;\{0,1\}//g' -e '/^[^=[]*=$/d' "$CONFIG_HOME/mimeapps.list"
  fi
  update-mime-database "$DATA_HOME/mime" >/dev/null 2>&1 || true
  update-desktop-database "$apps" >/dev/null 2>&1 || true
  say "Removing settings and cache"
  rm -rf -- "$CONFIG_HOME/quadrahq" "$CACHE_HOME/quadrahq" \
    "$CONFIG_HOME/ciderhq" "$CACHE_HOME/ciderhq" "$CONFIG_HOME/macoblox" "$CACHE_HOME/macoblox"
  if [[ -n $purge && -e $PREFIX ]]; then
    [[ $PREFIX == "$HOME"/?* ]] || die "Darling's prefix $PREFIX is not in your home folder, so it is left alone."
    say "Removing Darling's prefix (${PREFIX/#$HOME/\~}), with your Roblox sign-in"
    rm -rf -- "$PREFIX"
  fi
  say "Quadra is uninstalled."
  if command -v "$DARLING_EXECUTABLE" >/dev/null; then
    printf '    %s%s stays installed.%s\n' "$DIM" "$(darling_runtime_name)" "$RESET"
  fi
}

# --------------------------------------------------------------------- menu

# Drawn on the terminal's alternate screen, which gets its old contents back
# when the menu closes.
MENU_ON=''
MENU_SCREEN=''
menu_open() {
  MENU_ON=1
  if [[ ${TERM:-dumb} != dumb ]]; then
    MENU_SCREEN=1
    printf '\033[?1049h\033[?25l' >/dev/tty
  fi
}
menu_close() {
  [[ -n $MENU_ON ]] || return 0
  MENU_ON=''
  if [[ -n $MENU_SCREEN ]]; then
    MENU_SCREEN=''
    printf '\033[?25h\033[?1049l' >/dev/tty
  fi
}

banner() {
  printf '\n  %sQUADRA%s\n  quadrahq.org\n' "$BOLD" "$RESET"
}

# choose TEXT ITEM...: a menu of "label|hint" items below TEXT (printf %b).
# Sets CHOICE to the chosen item's index, or to -1 for quit.
CHOICE=-1
choose() {
  local text=$1
  shift
  local count=$# index=0 key rest item label hint i
  if [[ -z $MENU_SCREEN ]]; then
    {
      banner
      printf '\n%b\n\n' "$text"
      i=1
      for item; do
        printf '  %s. %s  %s\n' "$i" "${item%%|*}" "${item#*|}"
        i=$((i + 1))
      done
    } >/dev/tty
    while :; do
      printf '\n  Choose 1-%s [1], or q to quit: ' "$count" >/dev/tty
      IFS= read -r key </dev/tty || { CHOICE=-1; return; }
      [[ -n $key ]] || key=1
      case $key in
        q | Q) CHOICE=-1; return ;;
        [1-9]) if ((key <= count)); then CHOICE=$((key - 1)); return; fi ;;
      esac
    done
  fi
  while :; do
    {
      printf '\033[H\033[2J\n'
      banner
      printf '\n%b\n\n' "$text"
      i=0
      for item; do
        label=${item%%|*}
        hint=${item#*|}
        if ((i == index)); then
          printf '  %s %s %-22s%s %s\n' "$SELECTED" "$POINTER" "$label" "$RESET" "$hint"
        else
          printf '     %-22s %s%s%s\n' "$label" "$DIM" "$hint" "$RESET"
        fi
        i=$((i + 1))
      done
      printf '\n  %s%s%s\n' "$DIM" "$KEYS" "$RESET"
    } >/dev/tty
    IFS= read -rsn1 key </dev/tty || { CHOICE=-1; return; }
    case $key in
      $'\033')
        rest=''
        IFS= read -rsn2 -t 0.05 rest </dev/tty || true
        case $rest in
          '[A' | 'OA') index=$(((index + count - 1) % count)) ;;
          '[B' | 'OB') index=$(((index + 1) % count)) ;;
          '') CHOICE=-1; return ;;
        esac ;;
      k | K) index=$(((index + count - 1) % count)) ;;
      j | J) index=$(((index + 1) % count)) ;;
      [1-9]) if ((key <= count)); then CHOICE=$((key - 1)); return; fi ;;
      q | Q) CHOICE=-1; return ;;
      '') CHOICE=$index; return ;;
    esac
  done
}

menu_main() {
  local text first="Start setup|Review what will be installed"
  if is_installed; then
    text="  ${BOLD}Welcome back to Quadra${RESET}

  ${GOOD}${ON}${RESET} Version $(installed_version) is installed.
  Keep your launcher and compatibility libraries up to date.
  ${DIM}${DIR/#$HOME/\~}${RESET}"
    first="Update Quadra|Review the update plan"
  else
    text="  ${BOLD}Welcome to Quadra${RESET}
  ${DIM}First setup · 1 of 4${RESET}

  Play the macOS Roblox client on your Linux desktop.
  We'll prepare the launcher, Darling and the system tools.
  The launcher will guide you through installing Roblox and signing in."
  fi
  choose "$text" "$first" "Uninstall|Remove Quadra from this computer" "Quit|"
}

menu_install() {
  local operation='Install'
  is_installed && operation='Update'
  if [[ -z $DARLING_CHOICE_EXPLICIT ]]; then
    local text="  ${BOLD}Choose Darling · 2 of 4${RESET}

  Regular Darling uses your installed runtime or distro/upstream packages.
  QuadraHQ's CiderDarling includes our threading and graphics changes.
  CiderDarling currently needs a source build and its own first-time sign-in.
  Current selection: $(darling_runtime_name)"
    if [[ $DARLING_RUNTIME == ciderdarling ]]; then
      choose "$text" "QuadraHQ's CiderDarling|Keep the current selection" "Regular Darling|Use the upstream runtime" "Back|"
      case $CHOICE in 0) DARLING_RUNTIME=ciderdarling ;; 1) DARLING_RUNTIME=regular ;; *) return 1 ;; esac
    else
      choose "$text" "Regular Darling|Default; use the upstream runtime" "QuadraHQ's CiderDarling|Build QuadraHQ's runtime" "Back|"
      case $CHOICE in 0) DARLING_RUNTIME=regular ;; 1) DARLING_RUNTIME=ciderdarling ;; *) return 1 ;; esac
    fi
    load_darling_selection
  fi
  while :; do
    choose "  ${BOLD}Setup · 3 of 4${RESET}

$(setup_plan)" "Continue|Confirm this setup plan" "Back|Return to the welcome screen"
    [[ $CHOICE == 0 ]] || return 1
    choose "  ${BOLD}Ready to ${operation,,} Quadra${RESET}
  ${DIM}Setup · 4 of 4${RESET}

  Destination: ${DIR/#$HOME/\~}
  Setup downloads the launcher and builds the compatibility libraries.
  You'll see progress for each step. System packages may request sudo.

  ${DIM}Begin when you're ready.${RESET}" \
      "$operation Quadra|Begin setup" "Back|Review the plan again"
    case $CHOICE in
      0) return 0 ;;
      1) ;;
      *) return 1 ;;
    esac
  done
}

# The uninstall screen. Sets PURGE; false for "back".
PURGE=''
menu_uninstall() {
  local where=${DIR/#$HOME/\~} prefix=${PREFIX/#$HOME/\~}
  choose "  ${BOLD}Uninstall removes${RESET}
    ${BULLET} $where (the launcher, Roblox, Studio)
    ${BULLET} the app menu entries, icons and the quadrahq command
    ${BULLET} settings and cache

  ${DIM}Darling stays installed. Its prefix, $prefix, holds your Roblox sign-in.${RESET}" \
    "Uninstall|keep $prefix" "Uninstall everything|also delete $prefix" "Back|"
  case $CHOICE in
    0)
      PURGE=''
      return 0 ;;
    1)
      choose "  ${BAD}Delete $prefix?${RESET}

  It is Darling's macOS home folder: your Roblox sign-in, and anything
  else installed or saved in Darling, goes with it." \
        "No, go back|" "Yes, delete it|"
      [[ $CHOICE == 1 ]] || return 1
      PURGE=1
      return 0 ;;
    *) return 1 ;;
  esac
}

usage() {
  cat <<USAGE
Quadra installer

  install.sh               a menu in a terminal; without one, install or update
  install.sh --install     review the setup plan, then install or update
  install.sh --update      same as --install
  install.sh --install --yes
                           install or update without setup prompts
  install.sh --darling regular
                           choose regular Darling (default on first install)
  install.sh --darling ciderdarling
                           choose QuadraHQ's published Darling runtime
                           source builds still ask for terminal confirmation
  install.sh --install-runtime --darling ciderdarling
                           install only the runtime, keeping the current selection
                           (an update of the selected runtime switches to it)
  install.sh --darling ciderdarling --from-source
                           compile CiderDarling instead of downloading its
                           prebuilt build
  install.sh --pinned-runtime
                           use the bundled runtime pin without an online check
  install.sh --runtime-release FILE --darling ciderdarling --install-runtime
                           install the exact published release described by FILE
  install.sh --replace-incomplete-runtime
                           remove an interrupted CiderDarling installation without
                           asking, then build it again
  install.sh --uninstall   remove Quadra (asks first, unless --yes)
  install.sh --uninstall --purge
                           also delete the selected Darling prefix (Roblox sign-in)

With curl, options go after "bash -s --":
  curl -fsSL https://quadrahq.org/install.sh | bash -s -- --darling ciderdarling
  curl -fsSL https://quadrahq.org/install.sh | bash -s -- --uninstall

Updates keep your saved runtime choice. DARLING_BUILD_JOBS defaults to auto:
available CPU threads capped by memory headroom; set a positive count to override.
USAGE
}

main() {
  local action='' assume_yes='' reviewed='' arg
  while (($#)); do
    arg=$1
    case $arg in
      --install | --update) action=install ;;
      --install-runtime) action=runtime ;;
      --uninstall) action=uninstall ;;
      --purge) PURGE=1 ;;
      -y | --yes) assume_yes=1 ;;
      --replace-incomplete-runtime) REPLACE_INCOMPLETE_RUNTIME=1 ;;
      --from-source) CIDER_DARLING_FROM_SOURCE=1 ;;
      --pinned-runtime) CIDER_DARLING_PINNED=1 ;;
      --runtime-release)
        (($# >= 2)) || die "--runtime-release needs a release metadata file."
        CIDER_DARLING_RELEASE_FILE=$2
        shift ;;
      --darling)
        (($# >= 2)) || die "--darling needs regular or ciderdarling."
        DARLING_RUNTIME=$2
        DARLING_CHOICE_EXPLICIT=1
        shift ;;
      --darling=*) DARLING_RUNTIME=${arg#*=}; DARLING_CHOICE_EXPLICIT=1 ;;
      -h | --help)
        usage
        return 0 ;;
      *) die "Unknown option: $arg (see --help)" ;;
    esac
    shift
  done
  if [[ -n $DARLING_CHOICE_EXPLICIT && -z $DARLING_RUNTIME ]]; then
    die "--darling needs regular or ciderdarling."
  fi
  load_darling_selection
  [[ -z $CIDER_DARLING_RELEASE_FILE || $DARLING_RUNTIME == ciderdarling ]] ||
    die "--runtime-release requires --darling ciderdarling."
  # Package managers may ask questions; with curl | bash stdin is this script.
  if [[ ! -t 0 ]] && (: </dev/tty) 2>/dev/null; then exec </dev/tty; fi
  [[ $EUID -ne 0 ]] || die "Run this as your user, not root. sudo is used when needed."
  local terminal=''
  [[ -t 0 && -t 1 ]] && terminal=1

  if [[ -z $action && -n $terminal && -z $assume_yes ]]; then
    trap 'menu_close' EXIT
    trap 'menu_close; exit 130' INT TERM
    menu_open
    while [[ -z $action ]]; do
      menu_main
      case $CHOICE in
        0) if menu_install; then action=install; reviewed=1; fi ;;
        1) if menu_uninstall; then action=uninstall; fi ;;
        *) action=quit ;;
      esac
    done
    menu_close
    [[ $action == quit ]] || banner
  elif [[ $action == install && -n $terminal && -z $assume_yes ]]; then
    trap 'menu_close' EXIT
    trap 'menu_close; exit 130' INT TERM
    menu_open
    if ! menu_install; then
      menu_close
      say "Setup cancelled."
      return 0
    fi
    reviewed=1
    menu_close
    banner
  elif [[ $action == uninstall && -z $assume_yes ]]; then
    [[ -n $terminal ]] || die "Not uninstalling without a terminal to ask in; add --yes."
    local answer='' what="Quadra"
    [[ -n $PURGE ]] && what+=" and Darling's prefix ${PREFIX/#$HOME/\~}"
    printf 'Remove %s? [y/N] ' "$what"
    IFS= read -r answer || true
    if [[ $answer != [Yy]* ]]; then
      say "Nothing removed."
      return 0
    fi
  fi

  case ${action:-install} in
    install)
      if [[ -z $reviewed ]]; then
        banner
        printf '\n'
        setup_plan
      fi
      do_install ;;
    uninstall) do_uninstall "$PURGE" ;;
    runtime) banner; do_install_runtime ;;
    quit) ;;
  esac
}

main "$@"; exit
