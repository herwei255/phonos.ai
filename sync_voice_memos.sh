#!/bin/bash
# ── Auto-sync Voice Memos from Apple Voice Memos app ─────────────────────────
#
# Apple stores Voice Memos at this path on macOS:
#   ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/
#
# This script copies any new .m4a files from that folder into voice_memos/.
# Run it manually, or set it up as a cron job (see below).
#
# SETUP AS CRON (runs every 5 minutes):
#   crontab -e
#   Then paste this line (adjust the path):
#   */5 * * * * /Users/hw/Code/meeting-notes-tool/sync_voice_memos.sh
#
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
DEST="$SCRIPT_DIR/voice_memos"

mkdir -p "$DEST"

# Check if Apple Voice Memos folder exists
if [ ! -d "$SOURCE" ]; then
  echo "Apple Voice Memos folder not found at:"
  echo "  $SOURCE"
  echo ""
  echo "If you're on a newer macOS, try:"
  echo "  ~/Library/Application Support/com.apple.voicememos/Recordings/"
  echo ""
  echo "You can find it by running:"
  echo "  find ~/Library -name '*.m4a' -path '*voicememos*' -o -name '*.m4a' -path '*VoiceMemos*' 2>/dev/null | head -5"
  exit 1
fi

# Copy new files (skip existing ones)
COUNT=0
for f in "$SOURCE"/*.m4a; do
  [ -f "$f" ] || continue
  BASENAME="$(basename "$f")"
  if [ ! -f "$DEST/$BASENAME" ]; then
    cp "$f" "$DEST/$BASENAME"
    COUNT=$((COUNT + 1))
    echo "  Copied: $BASENAME"
  fi
done

if [ $COUNT -eq 0 ]; then
  echo "No new voice memos to sync."
else
  echo "Synced $COUNT new voice memo(s)."
fi
