import os
import sys
import time
import requests
from datetime import datetime, timezone


# Environment Variables
USERNAME = os.environ.get("RIJEXAMEN_USER")
PASSWORD = os.environ.get("RIJEXAMEN_PASS")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL") or os.environ.get("WEBHOOK_URL")
CENTER_ID = os.environ.get("CENTER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
CANDIDATE_ID = os.environ.get("CANDIDATE_ID")

DEBUG = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
TEST_WEBHOOK = os.environ.get("TEST_WEBHOOK", "false").lower() in ("true", "1", "yes")

TARGET_DATE_LIMIT = os.environ.get("TARGET_DATE_LIMIT", "2026-09-01")
TOKEN_URL = "https://rijexamen.km.be/api/oauth/token"
SLOT_URL = "https://rijexamen.km.be/api/scheduler/slot"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Origin": "https://rijexamen.km.be",
    "Referer": "https://rijexamen.km.be/login"
})

def debug_dump(res: requests.Response):
    """Dump volledige HTTP request & response info naar de console."""
    if not DEBUG:
        return
    
    req = res.request
    print("\n" + "=" * 60)
    print(f"🐛 [DEBUG] OUTGOING REQUEST: {req.method} {req.url}")
    print("--- Request Headers:")
    for k, v in req.headers.items():
        print(f"  {k}: {v}")
    if req.body:
        print("--- Request Body:")
        print(f"  {req.body}")
    
    print(f"\n🐛 [DEBUG] INCOMING RESPONSE: HTTP {res.status_code}")
    print("--- Response Headers:")
    for k, v in res.headers.items():
        print(f"  {k}: {v}")
    print("--- Response Body:")
    print(f"  {res.text}")
    print("=" * 60 + "\n")

def send_discord_embed(title: str, description: str, color: int, fields: list = None, ping: bool = False):
    if not WEBHOOK_URL:
        print("[WARN] No Webhook URL configured, skipping notification.")
        return

    payload = {
        "content": "@everyone" if ping else None,
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields or [],
                "footer": {
                    "text": f"systemd • rijexamen-watcher • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                }
            }
        ]
    }

    try:
        res = session.post(WEBHOOK_URL, json=payload, timeout=10)
        debug_dump(res)
        res.raise_for_status()
    except Exception as e:
        print(f"[ERR] Webhook dispatch failed: {e}")

def get_token():
    payload = {
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
        "audience": "athena_fo"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        res = session.post(TOKEN_URL, data=payload, headers=headers, timeout=10)
        debug_dump(res)

        if res.status_code == 200:
            return res.json().get("access_token")

        err_body = res.text[:200]
        print(f"[AUTH_FAIL] HTTP {res.status_code}: {err_body}")
        send_discord_embed(
            title="`[KM_AUTH_FAIL]` Inloggen mislukt",
            description=f"Kon geen access token ophalen.\n```http\nHTTP {res.status_code}\n{err_body}\n```",
            color=0xE74C3C  # Red
        )
        return None
    except Exception as e:
        print(f"[AUTH_EXCEPT] {e}")
        send_discord_embed(
            title="`[KM_AUTH_CRASH]` Netwerkfout bij inloggen",
            description=f"```text\n{str(e)}\n```",
            color=0xE74C3C
        )
        return None

def main():
    if TEST_WEBHOOK:
        print("🧪 [TEST_MODE] Sending test notification to Discord...")
        send_discord_embed(
            title="`[KM_TEST_PING]` Webhook Test",
            description="Testbericht vanuit lokale instellingen.",
            color=0x9B59B6,  # Purple
            fields=[
                {"name": "STATUS", "value": "`OK`", "inline": True},
                {"name": "ENV", "value": "`Lokaal`", "inline": True},
                {"name": "Cut-off", "value": f"`{TARGET_DATE_LIMIT}`", "inline": True}
            ],
            ping=False
        )
        print("✅ Test notification dispatched. Exiting test run.")
        return

    if DEBUG:
        print("⚠️ [DEBUG_MODE_ACTIVE] Full HTTP dumps enabled.")

    now = datetime.now()
    # AANGEPAST: Trigger de heartbeat elk uur rond XX:00 t/m XX:04
    if now.minute < 5:
        send_discord_embed(
            title="`[KM_SYS_INFO-HEARTBEAT]` Scraper actief (Heartbeat)",
            description=f"Script draait nog.\nZoekt voor cut-off: `{TARGET_DATE_LIMIT}`",
            color=0x3498DB  # Blue
        )

    token = get_token()
    if not token:
        sys.exit(1)

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    page = 0
    slots_found = []

    while True:
        payload = {
            "centerId": CENTER_ID,
            "page": page,
            "startDateTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "timePeriods": None,
            "serviceIds": [SERVICE_ID],
            "showAll": True,
            "forDashboard": False,
            "candidateId": CANDIDATE_ID
        }

        try:
            res = session.post(SLOT_URL, json=payload, headers=headers, timeout=10)
            debug_dump(res)

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
                print("[API_WARN] HTTP 403 Forbidden")
                send_discord_embed(
                    title="`[KM_API_WARN]` Geen toegang (403)",
                    description=f"API weigert request op pagina `{page}`.",
                    color=0xF1C40F  # Yellow
                )
                break
            else:
                print(f"[API_ERR] HTTP {res.status_code}")
                send_discord_embed(
                    title="`[KM_API_ERR]` API Fout",
                    description=f"Fout op pagina `{page}`.\n```http\nHTTP {res.status_code}\n{res.text[:200]}\n```",
                    color=0xF1C40F
                )
                break
        except Exception as e:
            print(f"[EXCEPT] Slot lookup error on page {page}: {e}")
            send_discord_embed(
                title="`[KM_SLOT_CRASH]` Fout bij ophalen plekken",
                description=f"Gestopt op pagina `{page}`.\n```text\n{str(e)}\n```",
                color=0xE74C3C
            )
            sys.exit(1)

    early_slots = []
    max_date_obj = datetime.strptime(TARGET_DATE_LIMIT, "%Y-%m-%d")

    for slot in slots_found:
        start_time = slot.get('startTime')
        if start_time:
            try:
                date_obj = datetime.strptime(start_time[:10], "%Y-%m-%d")
                if date_obj < max_date_obj:
                    early_slots.append(slot)
            except ValueError:
                continue

    if early_slots:
        early_slots.sort(key=lambda x: x.get('startTime', ''))
        earliest_slot = early_slots[0].get('startTime', 'N/A')

        fields = [
            {"name": "Gevonden plekken", "value": f"`{len(early_slots)}`", "inline": True},
            {"name": "Cut-off datum", "value": f"`{TARGET_DATE_LIMIT}`", "inline": True},
            {"name": "Eerstvolgende", "value": f"`{earliest_slot}`", "inline": True},
            {"name": "Link KM", "value": "[rijexamen.km.be](https://rijexamen.km.be)", "inline": False}
        ]

        send_discord_embed(
            title="`[KM_SLOT_FOUND]` Plaats(en) gevonden!",
            description="Nieuwe data beschikbaar voor cut-off datum.",
            color=0x2ECC71,  # Green
            fields=fields,
            ping=True
        )
        print(f"[OK] Found {len(early_slots)} slots before {TARGET_DATE_LIMIT}. Earliest: {earliest_slot}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No slots found before {TARGET_DATE_LIMIT}.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {e}")
        send_discord_embed(
            title="`[FATAL_CRASH]` Script Fout",
            description=f"Onverwachte fout, script gestopt.\n```text\n{str(e)}\n```",
            color=0xE74C3C
        )
        sys.exit(1)
