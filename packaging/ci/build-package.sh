#!/usr/bin/env bash
# Run inside the target distro container with /src, /runtime and /out mounted.
set -euo pipefail
flavor=${1:?package flavor required}
case $flavor in
  arch)
    pacman -Syu --noconfirm --needed base-devel clang lld git python pkgconf sdl2 wayland
    useradd -m builder
    ;;
  ubuntu24.04)
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential debhelper dh-python python3 clang lld pkg-config libsdl2-dev libwayland-dev
    ;;
  fedora)
    dnf install -y rpm-build clang lld gcc-c++ python3 pkgconf-pkg-config SDL2-devel wayland-devel
    ;;
  *) exit 2 ;;
esac
mkdir -p /work
cp -a /src/. /work/
cd /work
version=$(python3 -c 'import json; print(json.load(open("packaging/release.json"))["version"])')
archive=/out/ciderhq-$version-source.tar.gz
digest=$(sha256sum "$archive"); digest=${digest%% *}
python3 - "$digest" <<'PY'
import json, sys
from pathlib import Path
path = Path('packaging/release.json')
data = json.loads(path.read_text())
data['sha256'] = sys.argv[1]
path.write_text(json.dumps(data, indent=2) + '\n')
PY
bash packaging/prepare-source.sh /work/prepared "$archive"
export DARLING_SYSROOT=/runtime
case $flavor in
  arch)
    chown -R builder: /work/prepared/aur
    su -m builder -c 'cd /work/prepared/aur/ciderhq && makepkg --printsrcinfo > .SRCINFO && makepkg --nodeps --noconfirm'
    cp /work/prepared/aur/ciderhq/ciderhq-*.pkg.tar.zst /out/
    cp /work/prepared/aur/ciderhq/PKGBUILD /out/ciderhq.PKGBUILD
    cp /work/prepared/aur/ciderhq/.SRCINFO /out/ciderhq.SRCINFO
    ;;
  ubuntu24.04)
    cd "/work/prepared/Cider-$version"
    dpkg-buildpackage -b -us -uc
    cp /work/prepared/ciderhq_*.deb /out/
    ;;
  fedora)
    rpmbuild --define '_topdir /work/prepared/rpm' -ba /work/prepared/rpm/SPECS/ciderhq.spec
    cp /work/prepared/rpm/RPMS/x86_64/*.rpm /out/
    cp /work/prepared/rpm/SRPMS/*.src.rpm /out/
    ;;
esac
chmod -R a+rX /out
