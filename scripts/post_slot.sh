#!/bin/bash
# Post slot runner — called by LaunchAgent
SLOT=$1
cd /Users/badboybank/auto-clip
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
source .venv/bin/activate
source .env 2>/dev/null || true

LOG=logs/post.log
MAX_RETRY=2

echo "$(date): === Post slot $SLOT started ===" >> $LOG

for attempt in $(seq 1 $MAX_RETRY); do
    if python3 post.py --long --slot "$SLOT" >> $LOG 2>&1; then
        echo "$(date): === Slot $SLOT SUCCESS ===" >> $LOG
        exit 0
    else
        echo "$(date): Slot $SLOT attempt $attempt failed" >> $LOG
        [ $attempt -lt $MAX_RETRY ] && sleep 120
    fi
done

echo "$(date): === Slot $SLOT FAILED ===" >> $LOG
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚠️ เงินงอก Slot $SLOT โพสไม่ได้! ดู logs/post.log" >> $LOG 2>&1
