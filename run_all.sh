#!/usr/bin/env bash
# One command from an empty folder: venv + pinned deps + install + tests + full factory run.
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m unittest discover -s tests -t .
nyc311 --config "${NYC311_CONFIG:-config/default.json}" -v run
