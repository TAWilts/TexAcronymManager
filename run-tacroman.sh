#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$ROOT/.venv/bin/tacroman" ]; then
  exec "$ROOT/.venv/bin/tacroman" "$@"
fi
if command -v tacroman >/dev/null 2>&1; then
  exec tacroman "$@"
fi

echo "TAcroMan is not installed. Run: bash install-linux.sh"
exit 1
