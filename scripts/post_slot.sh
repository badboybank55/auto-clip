#!/bin/bash
# Post slot runner — called by LaunchAgent
SLOT=$1
cd /Users/badboybank/auto-clip
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
source .venv/bin/activate
source .env 2>/dev/null || true

LOG=logs/post.log
MAX_RETRY=2

echo "$(date): === Post slot $SLOT started ===" >> $LOG

# Slot 0: ถ้าไม่มี output วันนี้ → รัน pipeline ก่อนอัตโนมัติ
if [ "$SLOT" = "0" ]; then
    TODAY=$(date +%Y%m%d)
    if ! ls output/${TODAY}*_long/long/videos/long.mp4 2>/dev/null | grep -q .; then
        echo "$(date): ไม่พบ output วันนี้ → รัน pipeline อัตโนมัติ..." >> $LOG
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=🔄 ไม่พบคลิปวันนี้ กำลัง generate ใหม่อัตโนมัติ... (โพสช้าประมาณ 1-2 ชั่วโมง)" >> /dev/null 2>&1
        bash scripts/run_pipeline.sh
        # ตรวจอีกครั้งหลัง pipeline เสร็จ
        if ! ls output/${TODAY}*_long/long/videos/long.mp4 2>/dev/null | grep -q .; then
            echo "$(date): Pipeline ยังพัง ข้าม slot นี้" >> $LOG
            curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -d "chat_id=${TELEGRAM_CHAT_ID}" \
                -d "text=❌ Pipeline พังซ้ำ โพสวันนี้ไม่ได้ ดู logs/pipeline.log" >> /dev/null 2>&1
            exit 1
        fi
        echo "$(date): Pipeline เสร็จแล้ว ดำเนินการโพสต่อ" >> $LOG
    fi
fi

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
