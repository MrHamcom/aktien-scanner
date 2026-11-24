#!/usr/bin/env bash
# One-time setup of Aktien-Scanner under WSL2 (Ubuntu 24.04).
# Safe to run again: existing parts are kept, missing parts are added.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
PROJECT_DIR="$(pwd)"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m    %s\033[0m\n' "$1"; }
fail() { printf '\033[1;31mFEHLER: %s\033[0m\n' "$1" >&2; exit 1; }

case "$PROJECT_DIR" in
  /mnt/*) fail "Bitte das Projekt im Linux-Teil ablegen (z. B. ~/aktien-scanner), nicht unter /mnt/c – sonst wird es sehr langsam." ;;
esac

step "1/5 Systempakete prüfen"
if ! python3 -c "import ensurepip" 2>/dev/null; then
  echo "    Das Paket python3.12-venv fehlt. Ubuntu fragt jetzt einmal nach deinem Ubuntu-Passwort."
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.12-venv
fi
ok "Python $(python3 --version | cut -d' ' -f2) bereit"

step "2/5 Python-Umgebung anlegen"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
ok ".venv bereit"

step "3/5 Programm und Abhängigkeiten installieren (dauert beim ersten Mal ein paar Minuten)"
.venv/bin/python -m pip install --quiet -e ".[dev]"
ok "installiert"

step "4/5 Selbsttest"
.venv/bin/scanner check
.venv/bin/python -m pytest -q
ok "Selbsttest bestanden"

step "5/5 Desktop-Verknüpfung anlegen"
chmod +x start.sh update.sh
DISTRO="${WSL_DISTRO_NAME:-Ubuntu-24.04}"
PS_SCRIPT=$(cat <<EOF
\$ProgressPreference = 'SilentlyContinue'
\$desktop = [Environment]::GetFolderPath('Desktop')
\$link = Join-Path \$desktop 'Aktien-Scanner.lnk'
\$shell = New-Object -ComObject WScript.Shell
\$s = \$shell.CreateShortcut(\$link)
\$s.TargetPath = "\$env:SystemRoot\\System32\\wsl.exe"
\$s.Arguments = '-d $DISTRO -e bash $PROJECT_DIR/start.sh'
\$s.WindowStyle = 7
\$s.Description = 'Aktien-Scanner starten'
\$s.Save()
Write-Output \$link
EOF
)
ENCODED=$(printf '%s' "$PS_SCRIPT" | iconv -f utf-8 -t utf-16le | base64 -w0)
if command -v powershell.exe >/dev/null 2>&1; then
  LINK=$(cd /mnt/c && powershell.exe -NoProfile -NonInteractive -EncodedCommand "$ENCODED" 2>/dev/null | tr -d '\r' | tail -n 1)
  ok "Verknüpfung angelegt: $LINK"
else
  echo "    powershell.exe nicht gefunden – Verknüpfung übersprungen. Start alternativ mit: ./start.sh"
fi

printf '\n\033[1;32mFertig.\033[0m Starte den Aktien-Scanner per Doppelklick auf „Aktien-Scanner“ auf dem Desktop.\n'
