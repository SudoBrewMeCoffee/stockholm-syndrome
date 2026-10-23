#!/bin/zsh
# On the PRIMARY Mac: push a heartbeat to the standby Mac every 60s while the watcher is alive.
#   zsh heartbeat-install.sh user@standby-host
# Requires passwordless SSH from primary -> standby (Tailscale SSH or an authorized key).
set -e
TARGET="$1"; [ -n "$TARGET" ] || { echo "usage: $0 user@standby-host"; exit 1; }
DEST=~/stockholm-syndrome; LABEL=com.stockholm.heartbeat
mkdir -p "$DEST"
cat > "$DEST/heartbeat.sh" <<EOF
#!/bin/zsh
pgrep -f stockholm.py >/dev/null || exit 0
ssh -o BatchMode=yes -o ConnectTimeout=10 $TARGET 'mkdir -p ~/stockholm-syndrome && date +%s > ~/stockholm-syndrome/primary.heartbeat' 2>/dev/null
EOF
chmod +x "$DEST/heartbeat.sh"
cat > ~/Library/LaunchAgents/$LABEL.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>$DEST/heartbeat.sh</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
plutil -lint ~/Library/LaunchAgents/$LABEL.plist
launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$LABEL.plist
echo "heartbeat -> $TARGET every 60s"
