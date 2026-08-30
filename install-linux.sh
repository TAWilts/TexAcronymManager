#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: python3 was not found."
  exit 1
fi

if ! "$PYTHON" -c "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1'); from gi.repository import Gtk, WebKit2" >/dev/null 2>&1; then
  cat <<'EOF'
ERROR: GTK 3 or WebKit2GTK 4.1 is missing.

On Debian/Ubuntu install the native WebView dependencies first:
  sudo apt install python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1

On other distributions install GTK 3, PyGObject, and WebKit2GTK 4.1 using the
distribution package manager.
EOF
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "[1/3] Creating virtual environment..."
  "$PYTHON" -m venv --system-site-packages "$VENV"
else
  echo "[1/3] Virtual environment already exists."
  if ! grep -Eq '^include-system-site-packages = true' "$VENV/pyvenv.cfg"; then
    echo "ERROR: $VENV cannot access the distribution-provided GTK bindings."
    echo "Remove this virtual environment and run install-linux.sh again."
    exit 1
  fi
fi

echo "[2/3] Updating pip..."
"$VENV/bin/python" -m pip install --upgrade pip

echo "[3/3] Installing TAcroMan..."
"$VENV/bin/python" -m pip install -e "$ROOT"

echo
echo "Linux setup complete. Start TAcroMan with:"
echo "  bash run-tacroman.sh"
