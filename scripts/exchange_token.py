#!/usr/bin/env python3
"""แลก Facebook short-lived token เป็น long-lived Page token"""
import getpass, os, sys, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

APP_ID = "1642617523657587"
current_token = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
if not current_token:
    print("ไม่พบ FACEBOOK_ACCESS_TOKEN ใน .env")
    sys.exit(1)

print("ใส่ App Secret (ไม่แสดงบนหน้าจอ):")
app_secret = getpass.getpass("")

# Step 1: แลก user token เป็น long-lived user token
r = requests.get("https://graph.facebook.com/oauth/access_token", params={
    "grant_type":       "fb_exchange_token",
    "client_id":        APP_ID,
    "client_secret":    app_secret,
    "fb_exchange_token": current_token,
})
if r.status_code != 200:
    print("Error:", r.json())
    sys.exit(1)

ll_user_token = r.json().get("access_token", "")
print(f"\nLong-lived user token ได้แล้ว ({r.json().get('expires_in', 0)//86400} วัน)")

# Step 2: ดึง Page Access Token (ไม่หมดอายุ)
r2 = requests.get("https://graph.facebook.com/v21.0/me/accounts", params={
    "access_token": ll_user_token
})
pages = r2.json().get("data", [])
page_token = ""
for p in pages:
    if p["id"] == "118604523332820":
        page_token = p["access_token"]
        print(f"Page token สำหรับ '{p['name']}' ได้แล้ว (ไม่หมดอายุ)")
        break

if not page_token:
    print("ไม่พบ Page 118604523332820")
    sys.exit(1)

# Step 3: อัพเดท .env
env_path = Path(__file__).parent.parent / ".env"
content = env_path.read_text()
for line in content.splitlines():
    if line.startswith("FACEBOOK_ACCESS_TOKEN=") or line.startswith("INSTAGRAM_ACCESS_TOKEN="):
        old_token = line.split("=", 1)[1]
        content = content.replace(old_token, page_token)

env_path.write_text(content)
print("\n✅ อัพเดท .env เรียบร้อย — Facebook + Instagram token ใช้ได้ไม่หมดอายุ")
