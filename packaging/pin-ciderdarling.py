#!/usr/bin/env python3
"""Pin a CiderDarling revision in install.sh, with its prebuilt archives.

  packaging/pin-ciderdarling.py <40-hex revision>

Reads the manifests of CiderDarling's CI release bin-<12 hex digits> and
writes the revision, its patch-series hash and the SHA-256 of each prebuilt
archive into install.sh (a flavor without an archive installs from source),
updates the pin in docs/DARLING_RUNTIMES.md and refreshes the website copy
of the installer. Nothing is committed.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RELEASES = "https://github.com/QuadraHQ/CiderDarling/releases/download"
FLAVORS = {"arch": "CIDER_DARLING_PREBUILT_ARCH", "ubuntu24.04": "CIDER_DARLING_PREBUILT_UBUNTU2404"}


def manifest(revision, flavor):
    url = f"{RELEASES}/bin-{revision[:12]}/ciderdarling-{revision}-x86_64-{flavor}.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def replace(text, name, value):
    pattern = re.compile(rf"^{name}=.*$", re.M)
    if len(pattern.findall(text)) != 1:
        sys.exit(f"install.sh must assign {name} exactly once")
    return pattern.sub(f"{name}={value}", text)


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]):
        sys.exit(__doc__.strip())
    revision = sys.argv[1]
    found = {flavor: manifest(revision, flavor) for flavor in FLAVORS}
    series = {data["patch_manifest_sha256"] for data in found.values() if data}
    if not series:
        sys.exit(f"No prebuilt archives in release bin-{revision[:12]} (has its CI build finished?)")
    if len(series) != 1:
        sys.exit("The flavors disagree about the patch series")
    for flavor, data in found.items():
        if data and (data.get("source_revision") != revision or data.get("flavor") != flavor
                     or not re.fullmatch(r"[0-9a-f]{64}", data.get("archive_sha256", ""))):
            sys.exit(f"The {flavor} manifest does not describe this revision")

    installer = ROOT / "install.sh"
    text = installer.read_text()
    old = re.search(r"^CIDER_DARLING_REVISION=([0-9a-f]{40})$", text, re.M).group(1)
    old_series = re.search(r"^CIDER_DARLING_MANIFEST=([0-9a-f]{64})$", text, re.M).group(1)
    text = replace(text, "CIDER_DARLING_REVISION", revision)
    text = replace(text, "CIDER_DARLING_MANIFEST", next(iter(series)))
    for flavor, name in FLAVORS.items():
        text = replace(text, name, found[flavor]["archive_sha256"] if found[flavor] else "''")
    installer.write_text(text)
    notes = ROOT / "docs/DARLING_RUNTIMES.md"
    notes.write_text(notes.read_text().replace(old, revision).replace(old_series, next(iter(series))))
    subprocess.run(["bash", str(ROOT / "website/build.sh")], check=True)
    for flavor in FLAVORS:
        state = f"{found[flavor]['archive_bytes'] / 1048576:.0f} MiB, glibc {found[flavor]['min_glibc']}+" \
            if found[flavor] else "none: source build"
        print(f"{flavor}: {state}")
    print(f"Pinned CiderDarling {revision[:12]} in install.sh; review and commit.")


if __name__ == "__main__":
    main()
