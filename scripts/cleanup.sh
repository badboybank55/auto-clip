#!/bin/bash
# ลบ output เก่าเกิน 3 วัน
find /Users/badboybank/auto-clip/output -maxdepth 1 -type d -mtime +3 -exec rm -rf {} + 2>/dev/null

# Rotate logs เกิน 5MB → เก็บไว้แค่ 500 บรรทัดล่าสุด
for log in pipeline post; do
    f="/Users/badboybank/auto-clip/logs/${log}.log"
    if [ -f "$f" ] && [ $(wc -c < "$f") -gt 5000000 ]; then
        tail -500 "$f" > "${f}.tmp" && mv "${f}.tmp" "$f"
    fi
done

echo "$(date): Cleanup done" >> /Users/badboybank/auto-clip/logs/cleanup.log
