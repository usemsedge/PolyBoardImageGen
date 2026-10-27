#!/usr/bin/env bash
# Install a `replayextractor` command that runs: python3 __main__.py "$@"
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
ENTRY="$REPO/__main__.py"

if [[ ! -f "$ENTRY" ]]; then
  echo "install-cli.sh: missing $ENTRY" >&2
  exit 1
fi

os="$(uname -s 2>/dev/null || echo unknown)"
case "$os" in
  Darwin)
    if [[ -d /opt/homebrew/bin && -w /opt/homebrew/bin ]]; then
      BIN="/opt/homebrew/bin"
    elif [[ -d /usr/local/bin && -w /usr/local/bin ]]; then
      BIN="/usr/local/bin"
    else
      BIN="${HOME}/.local/bin"
    fi
    ;;
  Linux)
    BIN="${HOME}/.local/bin"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    BIN="${HOME}/bin"
    ;;
  *)
    BIN="${HOME}/.local/bin"
    echo "install-cli.sh: unknown uname '$os'; installing to $BIN" >&2
    ;;
esac

mkdir -p "$BIN"
DEST="$BIN/replayextractor"

# Prefer python3; fall back to python (Windows Git Bash / some Linux).
if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "install-cli.sh: need python3 or python on PATH" >&2
  exit 1
fi

cat > "$DEST" <<EOF
#!/usr/bin/env bash
exec $PY "$ENTRY" "\$@"
EOF
chmod +x "$DEST"

echo "installed $DEST"
echo "  -> $PY $ENTRY"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    echo "add to PATH (not currently set):"
    echo "  export PATH=\"$BIN:\$PATH\""
    ;;
esac

echo "try:  replayextractor <finished-game-link> [-o out.json] [-s game.state]"
