import os
import requests
from datetime import datetime
import time

TARGET_DATE_LIMIT = "2026-09-15"

USERNAME = os.environ.get("RIJEXAMEN_USER")
PASSWORD = os.environ.get("RIJEXAMEN_PASS")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
CENTER_ID = os.environ.get("CENTER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
CANDIDATE_ID = os.environ.get("CANDIDATE_ID")

TOKEN_URL = "https://rijexamen.km.be/api/oauth/token"
SLOT_URL = "https://rijexamen.km.be/api/scheduler/slot"

def notify(msg):
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": msg})
        except:
            pass

def get_token():
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://rijexamen.km.be",
        "Referer": "https://rijexamen.km.be/login"
    }
    payload = {
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
        "audience": "athena_fo"
    }
    
    res = requests.post(TOKEN_URL, data=payload, headers=headers)
    if res.status_code == 200:
        return res.json().get("access_token")
    
    notify(f"ERROR: Login failed (HTTP {res.status_code})")
    return None

def main():
    now = datetime.now()
    if now.hour == 12 and now.minute < 5:
        notify(f"INFO: Scraper is active. Filtering slots before {TARGET_DATE_LIMIT}")

    token = get_token()
    if not token: 
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0)",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://rijexamen.km.be"
    }

    page = 0
    slots_found = []

    while True:
        payload = {
            "centerId": CENTER_ID,
            "page": page,
            "startDateTime": datetime.now().isoformat()[:19],
            "timePeriods": None,
            "serviceIds": [SERVICE_ID],
            "showAll": True,
            "forDashboard": False,
            "candidateId": CANDIDATE_ID
        }

        res = requests.post(SLOT_URL, json=payload, headers=headers)
        
        if res.status_code == 200:
            data = res.json()
            slot_map = data.get("bestFreeSlotMap", {})
            
            found = [s for dates in slot_map.values() if isinstance(dates, list) for s in dates]
            
            if found:
                slots_found.extend(found)
                page += 1
                time.sleep(1)
            else:
                break
        elif res.status_code == 403:
            notify("WARN: 403 Forbidden")
            break
        else:
            break

    early_slots = []
    max_date_obj = datetime.strptime(TARGET_DATE_LIMIT, "%Y-%m-%d")

    for slot in slots_found:
        start_time = slot.get('startTime')
        if start_time:
            date_obj = datetime.strptime(start_time[:10], "%Y-%m-%d")
            if date_obj < max_date_obj:
                early_slots.append(slot)

    if early_slots:
        early_slots.sort(key=lambda x: x.get('startTime', ''))
        earliest_slot = early_slots[0].get('startTime')
        
        msg = (
            f"🚨 **@everyone SLOT FOUND!** 🚨\n"
            f"Found **{len(early_slots)}** public slot(s) before {TARGET_DATE_LIMIT}!\n"
            f"Earliest available: **{earliest_slot}**\n"
            f"Book now: https://rijexamen.km.be"
        )
        
        notify(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify(f"FATAL: {e}")