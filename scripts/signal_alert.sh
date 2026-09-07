#!/usr/bin/env bash
# Plays the "amir_trade signal fired" alert sound (phone-incoming-call, chosen
# and confirmed by the user 2026-09-05 -- distinct from Claude's own
# notification sound, deliberately alarm-like so it pulls attention to the
# desk). Played 3x with short gaps so it's hard to miss.
set -euo pipefail
SOUND=/usr/share/sounds/freedesktop/stereo/phone-incoming-call.oga
for i in 1 2 3; do
    paplay "$SOUND" || true
    sleep 0.3
done
