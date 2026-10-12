#!/usr/bin/env bash
# Installs the Cider launcher for the current user: menu entry, icons
# and a `ciderhq` command. Run again after moving the project folder.
set -euo pipefail
launcher_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_dir=$(dirname -- "$launcher_dir")
data_home=${XDG_DATA_HOME:-$HOME/.local/share}
config_home=${XDG_CONFIG_HOME:-$HOME/.config}

if [[ $project_dir == "$data_home/MacOBlox" && ! -e $data_home/CiderHQ ]]; then
  mv -T --no-clobber -- "$project_dir" "$data_home/CiderHQ"
  [[ ! -e $project_dir ]] || { printf '%s\n' 'Cider migration destination is occupied.' >&2; exit 1; }
  project_dir=$data_home/CiderHQ
  launcher_dir=$project_dir/launcher
fi
for size in 16 22 24 32 48 64 128 256 512 1024; do
  install -Dm644 "$project_dir/branding/icons/ciderhq-$size.png" \
    "$data_home/icons/hicolor/${size}x${size}/apps/ciderhq.png"
done
# An earlier release installed a placeholder vector with this icon name.
rm -f -- "$data_home/icons/hicolor/scalable/apps/ciderhq.svg"

install -d "$HOME/.local/bin"
ln -sf "$launcher_dir/ciderhq-launcher" "$HOME/.local/bin/ciderhq"
if [[ -L $HOME/.local/bin/macoblox && $(readlink "$HOME/.local/bin/macoblox") == */macoblox-launcher ]]; then
  rm -- "$HOME/.local/bin/macoblox"
fi

# The launcher's path as a quoted Exec argument (Desktop Entry spec): a
# project folder with a space in its path broke the menu entries.
exec_path=${launcher_dir//\\/\\\\\\\\}
exec_path=${exec_path//\"/\\\\\"}
exec_path=${exec_path//\`/\\\\\`}
exec_path=${exec_path//\$/\\\\\$}
exec_path=\"${exec_path//\%/%%}/ciderhq-launcher\"

install -d "$data_home/applications"
cat > "$data_home/applications/org.ciderhq.Cider.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cider
Comment=Run the macOS Roblox client on Linux through Darling
Comment[ru]=Запуск клиента Roblox для macOS на Linux через Darling
GenericName=Roblox launcher
GenericName[ru]=Лаунчер Roblox
Exec=$exec_path
Icon=ciderhq
Terminal=false
Categories=Game;
Keywords=roblox;darling;
StartupNotify=true
DESKTOP

# Roblox links are LaunchServices protocol handoffs on macOS.  Keep a
# separate hidden entry for Linux so the complete URI is substituted into one
# launcher argument and can reach RobloxPlayer unchanged.
cat > "$data_home/applications/org.ciderhq.Cider.URI.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cider Roblox Link Handler
Comment=Open Roblox links in Cider
Exec=$exec_path %u
Icon=ciderhq
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/roblox;x-scheme-handler/roblox-player;
DESKTOP

# Roblox Studio (Windows version through Wine), also the handler of the
# roblox-studio: links and of roblox-studio-auth: that signs Studio in.
cat > "$data_home/applications/org.ciderhq.Cider.Studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Roblox Studio (Cider)
Comment=Roblox Studio through Wine
Comment[ru]=Roblox Studio через Wine
Exec=$exec_path --studio %u
Icon=ciderhq
Terminal=false
Categories=Development;
MimeType=x-scheme-handler/roblox-studio;x-scheme-handler/roblox-studio-auth;application/x-roblox-place;
StartupWMClass=robloxstudiobeta.exe
DESKTOP

# A shortcut to CiderDarling's settings, only while CiderDarling is installed
# (packaging/org.ciderhq.Cider.CiderDarling.desktop; the launcher keeps it in
# step when runtimes change later). Its marker line identifies our copy.
ciderdarling_entry=$data_home/applications/org.ciderhq.Cider.CiderDarling.desktop
ciderdarling_state=0
PYTHONPATH=$launcher_dir python3 -c '
import sys
from macoblox import runtime
try:
    installed = "ciderdarling" in runtime.installed_runtimes()
except Exception:
    sys.exit(2)
sys.exit(0 if installed else 1)' 2>/dev/null || ciderdarling_state=$?
ciderdarling_ours=''
if [[ ! -e $ciderdarling_entry && ! -L $ciderdarling_entry ]] ||
    { [[ ! -L $ciderdarling_entry ]] && grep -qsx 'X-CiderHQ-Managed=true' "$ciderdarling_entry"; }; then
  ciderdarling_ours=1  # absent, or ours: a user's own entry of that name stays
fi
if [[ $ciderdarling_state == 0 && -n $ciderdarling_ours ]]; then
  cat > "$ciderdarling_entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=CiderDarling Settings
Name[ru]=Настройки CiderDarling
Comment=Graphics card, runtime and diagnostics settings for CiderDarling
Comment[ru]=Видеокарта, среда и диагностика для CiderDarling
Exec=$exec_path --ciderdarling-settings
Icon=ciderhq
Terminal=false
Categories=Game;
Keywords=ciderdarling;darling;gpu;
StartupNotify=true
X-CiderHQ-Managed=true
DESKTOP
elif [[ $ciderdarling_state == 1 && -n $ciderdarling_ours && -e $ciderdarling_entry ]]; then
  rm -f -- "$ciderdarling_entry"
fi
# Place files (.rbxl, .rbxlx) as their own type, so file managers open them
# with Studio: no MIME database defines one.
install -Dm644 "$project_dir/packaging/org.ciderhq.Cider.xml" "$data_home/mime/packages/org.ciderhq.Cider.xml"
update-mime-database "$data_home/mime" 2>/dev/null || true
if command -v xdg-mime >/dev/null; then
  for type in x-scheme-handler/roblox-studio x-scheme-handler/roblox-studio-auth application/x-roblox-place; do
    xdg-mime default org.ciderhq.Cider.Studio.desktop "$type"
  done
  for type in x-scheme-handler/roblox x-scheme-handler/roblox-player; do
    xdg-mime default org.ciderhq.Cider.URI.desktop "$type"
  done
fi

# Old app IDs (org.macoblox.Launcher before 0.10, xyz.narez.MacOBlox before
# 0.15); removed after the new entries exist so menus that rescan on the
# first change (noctalia) do not miss them.
rm -f "$data_home/applications/org.macoblox.Launcher.desktop" \
  "$data_home/applications/wtf.aubree.MacOBlox.desktop" \
  "$data_home/applications/wtf.aubree.MacOBlox.URI.desktop" \
  "$data_home/applications/wtf.aubree.MacOBlox.Studio.desktop" \
  "$data_home/applications/macoblox-roblox-window.desktop" \
  "$data_home/mime/packages/wtf.aubree.MacOBlox.xml" \
  "$data_home/applications/xyz.narez.MacOBlox.desktop" \
  "$data_home/applications/xyz.narez.MacOBlox.Studio.desktop" \
  "$data_home/mime/packages/xyz.narez.MacOBlox.xml"
if [ -f "$config_home/mimeapps.list" ]; then
  sed -i -e 's/xyz\.narez\.MacOBlox\.Studio\.desktop;\{0,1\}//g' \
    -e 's/wtf\.aubree\.MacOBlox\.Studio\.desktop;\{0,1\}//g' \
    -e 's/wtf\.aubree\.MacOBlox\.URI\.desktop;\{0,1\}//g' \
    -e '/^[^=[]*=$/d' "$config_home/mimeapps.list"
fi

# The game window itself (X11 class RobloxPlayer) gets the same icon in docks.
cat > "$data_home/applications/ciderhq-roblox-window.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Roblox (Cider)
Exec=$exec_path
Icon=ciderhq
NoDisplay=true
StartupWMClass=RobloxPlayer
DESKTOP

update-desktop-database "$data_home/applications" 2>/dev/null || true
# No gtk-update-icon-cache: with -t it wrote a cache into the user's icon
# folder that other apps do not update, which can hide their icons.
echo "Cider installed: find it in the app menu or run: ciderhq"
