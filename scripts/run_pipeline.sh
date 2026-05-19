#!/bin/bash
# Daily pipeline runner — called by LaunchAgent at 05:50
cd /Users/badboybank/auto-clip
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
source .venv/bin/activate
source .env 2>/dev/null || true

LOG=logs/pipeline.log
MAX_RETRY=3
SUCCESS=0

echo "$(date): === Pipeline started ===" >> $LOG

for attempt in $(seq 1 $MAX_RETRY); do
    echo "$(date): Attempt $attempt/$MAX_RETRY" >> $LOG
    if python3 main.py --long --auto >> $LOG 2>&1; then
        echo "$(date): === Pipeline SUCCESS ===" >> $LOG
        SUCCESS=1
        break
    else
        echo "$(date): Attempt $attempt failed" >> $LOG
        if [ $attempt -lt $MAX_RETRY ]; then
            echo "$(date): Waiting 3 minutes before retry..." >> $LOG
            sleep 180
        fi
    fi
done

if [ $SUCCESS -eq 0 ]; then
    echo "$(date): === Pipeline FAILED after $MAX_RETRY attempts ===" >> $LOG
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=⚠️ เงินงอก Pipeline พัง! ดู logs/pipeline.log" >> $LOG 2>&1
fi
