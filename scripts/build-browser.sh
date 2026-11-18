#!/usr/bin/env bash
set -euo pipefail
# Keep flags, SDK discovery and artifact selection in the shared Node builder.
exec node "$(dirname "$0")/build-browser.mjs" "$@"
