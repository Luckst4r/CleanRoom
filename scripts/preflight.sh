#!/usr/bin/env bash
# CleanRoom preflight — checks the Mac mini has what it needs before deploying.
# Safe to run repeatedly. Run from the repo root:  bash scripts/preflight.sh
set -u

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; }

echo "== System =="
uname -srm
sw_vers 2>/dev/null | sed 's/^/  /' || warn "sw_vers not found (not macOS?)"

echo "== Tooling =="
for cmd in python3 pip3 ollama ffmpeg pio; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd -> $(command -v "$cmd")"
  else
    case "$cmd" in
      ffmpeg) warn "ffmpeg missing (optional: used to test RTSP by hand). brew install ffmpeg" ;;
      pio)    warn "pio (PlatformIO) missing — needed only to flash the screen. Install the PlatformIO VS Code extension or: pip3 install platformio" ;;
      ollama) bad  "ollama missing — REQUIRED for local detection. Install from https://ollama.com" ;;
      *)      bad  "$cmd missing" ;;
    esac
  fi
done

echo "== Ollama =="
if command -v ollama >/dev/null 2>&1; then
  if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama server is running (http://localhost:11434)"
    models=$(curl -fsS http://localhost:11434/api/tags | tr ',' '\n' | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | paste -sd' ' -)
    [ -n "$models" ] && ok "models pulled: $models" || warn "no models pulled yet — run: ollama pull qwen2.5vl:7b"
  else
    warn "Ollama installed but server not reachable — start the Ollama app, or run: ollama serve"
  fi
fi

echo "== Python deps =="
if python3 -c "import cv2, flask, requests, yaml, dotenv" 2>/dev/null; then
  ok "detector dependencies importable"
else
  warn "detector deps not installed yet — run: pip3 install -r detector/requirements.txt"
fi

echo
echo "Done. Resolve any ✗ (required) before deploying; ! items are situational."
