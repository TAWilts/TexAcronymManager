#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/vscode-extension"

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm was not found. Install Node.js LTS first."
  exit 1
fi

echo "[1/3] Installing/updating Node dependencies..."
npm install --no-fund --no-audit
echo "[2/3] Running extension tests..."
npm test
echo "[3/3] Building VSIX package..."
npm run package

echo "TAcroMan VS Code extension build complete."
ls -1t tacroman-vscode-*.vsix 2>/dev/null | head -n 1 || true
