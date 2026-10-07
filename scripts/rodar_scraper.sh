#!/usr/bin/env bash
# Roda o scraper na sua máquina (Mac/Linux). Agende no cron, ex.:
#   0 7 * * * /caminho/olx-monitor/scripts/rodar_scraper.sh
cd "$(dirname "$0")/.."
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" -m app.jobs.daily --skip-if-done-today >> scraper.log 2>&1
