#!/usr/bin/env bash
# Starts the Aktien-Scanner UI and opens it in the Windows browser.
# Used by the desktop shortcut. Closing the (minimised) window stops the scanner.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PORT=$(.venv/bin/python -c "from scanner.config import load_config; print(load_config().ui.port)")
URL="http://localhost:${PORT}"

is_up() { (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; }

open_browser() {
  if command -v cmd.exe >/dev/null 2>&1; then
    (cd /mnt/c && cmd.exe /c start "" "$URL") >/dev/null 2>&1 || true
  else
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
}

# Already running: just open the browser.
if is_up; then
  open_browser
  exit 0
fi

# Open the browser as soon as the server answers.
(
  for _ in $(seq 1 120); do
    if is_up; then open_browser; exit 0; fi
    sleep 0.5
  done
) &

echo "Aktien-Scanner läuft auf ${URL} – dieses Fenster schließen, um ihn zu beenden."
exec .venv/bin/aktien-scanner
