#!/bin/zsh
# Install Stockholm as a macOS LaunchAgent (starts now, restarts on crash, self-removes at STOCK_RUN_UNTIL).
#
#   zsh install.sh                       # primary watcher
#   STANDBY=1 zsh install.sh             # hot standby (polls only when the primary's heartbeat is stale)
#
# Put your config in ./stockholm.env first (copy stockholm.env.example). Values go into the plist.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.stockholm.watch
DEST=~/stockholm-syndrome
[ -f "$HERE/stockholm.env" ] || { echo "copy stockholm.env.example to stockholm.env and fill it in"; exit 1; }
mkdir -p "$DEST" ~/Library/LaunchAgents
cp "$HERE/stockholm.py" "$DEST/stockholm.py"; chmod +x "$DEST/stockholm.py"
rm -f "$DEST/state.json"
/usr/bin/python3 -m py_compile "$DEST/stockholm.py"

ENVXML=""
while IFS='=' read -r k v; do
  [[ -z "$k" || "$k" == \#* ]] && continue
  ENVXML+="<key>$k</key><string>${v//&/&amp;}</string>"
done < "$HERE/stockholm.env"
if [ -n "$STANDBY" ]; then
  ENVXML+="<key>STOCK_STANDBY_HEARTBEAT</key><string>$DEST/primary.heartbeat</string><key>STOCK_HEARTBEAT</key><string>0</string>"
fi

cat > ~/Library/LaunchAgents/$LABEL.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$DEST/stockholm.py</string></array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$DEST/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DEST/launchd.err.log</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string>$ENVXML</dict>
</dict></plist>
EOF
plutil -lint ~/Library/LaunchAgents/$LABEL.plist
launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$LABEL.plist
sleep 8
launchctl print gui/$(id -u)/$LABEL | grep -E "state|pid" | head -2
tail -3 "$DEST/stockholm.log"
echo
echo "Stop early:  launchctl bootout gui/\$(id -u)/$LABEL"
