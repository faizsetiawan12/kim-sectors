#!/usr/bin/env bash
# KIM Sectors - Daily Post-Market Cron Entrypoint
# Runs Monday-Friday after IDX market close (16:15 Asia/Jakarta)
# Schedule: CRON_TZ=Asia/Jakarta; 15 16 * * 1-5
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

# Ensure runtime output directories exist
mkdir -p output/reports/daily output/logs data/cache

# Use active python or specified interpreter
PYTHON_BIN="${PYTHON_BIN:-python}"

export TZ="Asia/Jakarta"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S %Z')] Starting KIM Sectors Daily Pipeline ==="
"${PYTHON_BIN}" main.py run-daily "$@"
EXIT_CODE=$?
echo "=== [$(date '+%Y-%m-%d %H:%M:%S %Z')] KIM Sectors Daily Pipeline finished with exit code ${EXIT_CODE} ==="

exit ${EXIT_CODE}
