#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: python3 was not found."
  exit 1
fi

if ! "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
  cat <<'EOF'
ERROR: Python's Tk bindings are missing.

Install them first, for example:
  Debian/Ubuntu: sudo apt install python3-tk python3-venv
  Fedora:        sudo dnf install python3-tkinter
  Arch Linux:    sudo pacman -S tk
EOF
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "[1/3] Creating virtual environment..."
  "$PYTHON" -m venv "$VENV"
else
  echo "[1/3] Virtual environment already exists."
fi

echo "[2/3] Updating pip..."
"$VENV/bin/python" -m pip install --upgrade pip

echo "[3/3] Installing TAcroMan..."
"$VENV/bin/python" -m pip install -e "$ROOT"

echo
echo "Linux setup complete. Start TAcroMan with:"
echo "  bash run-tacroman.sh"
