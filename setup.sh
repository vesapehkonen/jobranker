#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

echo "Setting up Job Helper..."

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

echo "Installing Python dependencies..."
"$PIP" install --upgrade pip

if [ -f requirements.txt ]; then
  "$PIP" install -r requirements.txt
else
  echo "ERROR: requirements.txt not found."
  exit 1
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  else
    cat > .env <<EOF
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini
API_TOKEN=change-me
HOST=127.0.0.1
PORT=8000
EOF
    echo "Created .env"
  fi
fi

if grep -q "API_TOKEN=change-me" .env; then
  TOKEN="$("$PY" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  sed -i "s/API_TOKEN=change-me/API_TOKEN=$TOKEN/" .env
  echo "Generated API_TOKEN in .env"
fi

if [ -d extension ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Installing and building browser extension..."
    cd extension

    if [ ! -f package.json ]; then
      npm init -y
      npm install -D typescript @types/chrome
    else
      npm install
    fi

    npx tsc

    cd "$ROOT_DIR"
  else
    echo "WARNING: npm not found. Skipping extension build."
  fi
fi

echo
echo "Setup complete."
echo "Next:"
echo "1. Edit .env and set OPENAI_API_KEY"
echo "2. Run ./start.sh"
echo "3. Add API_TOKEN from .env to the extension settings"

