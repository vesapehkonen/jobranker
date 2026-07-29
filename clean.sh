#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

rm -f -- *~ .#* \#*\#
rm -f -- extension/*~ extension/src/*~ templates/*~ static/*~

rm -rf -- __pycache__ tests/__pycache__
rm -rf -- extension/node_modules

echo "Removed Python caches, Node dependencies, and editor files."
echo "Preserved .env, .venv, data, package-lock.json, and extension/dist."
