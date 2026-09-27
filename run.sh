#!/usr/bin/env bash
# DFS Lab launcher.
#   ./run.sh              open the app in your browser
#   ./run.sh test         run the checks (pytest)
#   ./run.sh import ...   command-line import, e.g. ./run.sh import 2026-wk02-main ~/Downloads/DKEntries.csv
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "DFS Lab needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and try again."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up DFS Lab (one time, about a minute)..."
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  touch .venv/.installed
fi

case "${1:-app}" in
  app)  exec .venv/bin/streamlit run app/app.py --server.address localhost --browser.gatherUsageStats false ;;
  test) shift; exec .venv/bin/python -m pytest "$@" ;;
  *)    exec .venv/bin/python -m core.cli "$@" ;;
esac
