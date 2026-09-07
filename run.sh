#!/usr/bin/env bash
# Thin wrapper around the mt5bridge CLI package. Usage:
#   ./run.sh state
#   ./run.sh tick gold
#   ./run.sh analyze gold --tf M1 M5 M15
#   ./run.sh place gold --type buy_limit --entry 4433.0 --sl 4430.5 --tp 4440.0
#
# Machine-specific paths come from environment variables (see .env.example).
# A git-ignored .env file next to this script is auto-loaded if present.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.env"
    set +a
fi

# Wine prefix that holds the MT5 terminal + the Windows Python. Override with
# MT5_WINEPREFIX in .env. Set to an empty string to run against a native
# (non-Wine) Python that has the MetaTrader5 package installed.
MT5_WINEPREFIX="${MT5_WINEPREFIX:-$HOME/.mt5}"

if [ -n "$MT5_WINEPREFIX" ]; then
    export WINEPREFIX="$MT5_WINEPREFIX"
    WINE_PYTHON="${MT5_WINE_PYTHON:-../Python311/python.exe}"
    cd "$WINEPREFIX/drive_c"
    exec wine "$WINE_PYTHON" -m mt5bridge.cli "$@"
else
    cd "$PROJECT_DIR"
    exec "${MT5_PYTHON:-python3}" -m mt5bridge.cli "$@"
fi
