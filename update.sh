#!/usr/bin/env bash
# Fetches the latest version from GitHub and reinstalls dependencies.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
git pull --ff-only
.venv/bin/python -m pip install --quiet -e ".[dev]"
.venv/bin/scanner check
.venv/bin/python -m pytest -q
printf '\n\033[1;32mAktualisiert.\033[0m Falls der Scanner läuft: Fenster schließen und neu starten.\n'
