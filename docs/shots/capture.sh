#!/bin/bash
cd /mnt/c/ClaudeCode/kali-gui/docs/shots
[ -f test_picker.png ] && mv -f test_picker.png shot_tools.png
shoot() {
  timeout 40 chromium --headless --no-sandbox --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=1 --window-size=1360,900 --virtual-time-budget=7000 \
    --screenshot="$1" "$2" >/dev/null 2>&1
  echo "$1 -> $(stat -c%s "$1" 2>/dev/null) bytes"
}
shoot shot_dashboard.png 'http://127.0.0.1:8777/#dashboard'
shoot shot_brain.png     'http://127.0.0.1:8777/#brain-red'
ls -la shot_*.png
