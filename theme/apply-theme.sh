#!/usr/bin/env bash
# Apply a Claude colour scheme to the MetaTrader 5 Wine prefix.
#
#   ./theme/apply-theme.sh dark      # Claude warm near-black
#   ./theme/apply-theme.sh light     # Claude cream paper
#   ./theme/apply-theme.sh revert    # restore the Wine colours captured on first run
#
# What this touches (see theme/README.md for the full scope story):
#   * HKCU\Control Panel\Colors        -> Wine-drawn frame, dialogs, menus,
#                                         scrollbars, tooltips, standard controls
#   * ...\Themes\Personalize\AppsUseLightTheme -> MT5's own dark/light panel set
#
# It does NOT touch the chart surface (that's Premium_Candles*.tpl, applied by
# right-click -> Templates) and it cannot recolour MT5's custom-drawn panels
# beyond MetaQuotes' own light/dark palette.
#
# Restart MetaTrader 5 after running this -- Wine only re-reads these on start.
set -euo pipefail

THEME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$THEME_DIR")"
export WINEPREFIX="${MT5_WINEPREFIX:-$HOME/.mt5}"
BACKUP="$THEME_DIR/_wine-colors-backup.reg"

mode="${1:-}"
case "$mode" in
    dark|light) reg="$THEME_DIR/claude-$mode.reg" ;;
    revert)     reg="$BACKUP" ;;
    *) echo "usage: $0 {dark|light|revert}" >&2; exit 2 ;;
esac
[ -f "$reg" ] || { echo "missing: $reg" >&2; exit 1; }

if pgrep -f "terminal64.exe" >/dev/null 2>&1; then
    echo "note: MetaTrader 5 is running -- the scheme imports now but only takes"
    echo "      effect after you fully close and reopen the terminal."
fi

echo "importing $(basename "$reg") into $WINEPREFIX ..."
wine reg import "$(winepath -w "$reg" 2>/dev/null || echo "$reg")" 2>/dev/null \
    || wine regedit /S "$reg"

if [ "$mode" = "revert" ]; then
    # backup only held Control Panel\Colors; drop the dark-mode hint too
    wine reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize" \
        /v AppsUseLightTheme /t REG_DWORD /d 1 /f >/dev/null 2>&1 || true
    wine reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize" \
        /v SystemUsesLightTheme /t REG_DWORD /d 1 /f >/dev/null 2>&1 || true
    echo "reverted Wine colours to the captured backup."
else
    echo "applied Claude $mode."
    echo "next: right-click any chart -> Templates -> Premium_Candles$([ "$mode" = light ] && echo _Light)"
fi
echo "then restart MetaTrader 5."
