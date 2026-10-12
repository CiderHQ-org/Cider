#!/bin/sh
# Cider inside the Flatpak: a Darling prefix of its own, Darling
# without root (darling-noroot.c) and the shim built with the package.
export DPREFIX="${DPREFIX:-$XDG_DATA_HOME/darling}"
export MACOBLOX_NOROOT_LIB=/app/lib/ciderhq/darling-noroot.so
export MACOBLOX_PID1_DYLIB=/app/lib/ciderhq/launchd_pid1.dylib
export MACOBLOX_PREBUILT_SHIM=/app/lib/ciderhq/shim
exec python3 /app/share/ciderhq/launcher/ciderhq-launcher "$@"
