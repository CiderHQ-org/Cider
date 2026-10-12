#!/usr/bin/env bash
# Include the current installer in the static site's public output.
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
install -m644 "$project/install.sh" "$project/website/dist/install.sh"
