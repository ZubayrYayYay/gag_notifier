import asyncio
import json
import aiohttp
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import os

# === CONFIG ===
load_dotenv()  # Load environment variables from .env file
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WATCHLIST_FILE = "gag_watchlist.json"

previous_stock = {}

def load_watchlist():
    path = Path(WATCHLIST_FILE)
    if not path.exists():
        path.write_text("[]")
    try:
        return set(json.loads(path.read_text()))
    except Exception as e:
        print(f"⚠️ Load watchlist error: {e}")
        return set()

async def send_telegram_notification(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    async with aiohttp.ClientSession() as s:
        await s.post(url, data=payload)

def combine_items(items, key_qty="value"):
    d = defaultdict(int)
    for item in items:
        name = item.get("name")
        qty = item.get(key_qty, 0) or 0
        d[name] += qty
    return [{"name": name, "quantity": qty} for name, qty in d.items()]

def seconds_until_next_5_min_offset_1():
    now = datetime.now()
    minute = ((now.minute // 5) + 1) * 5 + 1
    hour = now.hour + (minute // 60)
    minute %= 60
    hour %= 24
    next_t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (next_t - now).total_seconds()
    if delta <= 0:
        # Add 5 minutes to ensure positive sleep time
        next_t += timedelta(minutes=5)
        delta = (next_t - now).total_seconds()
    return delta

def seconds_until_next_5_min_offset_30():
    now = datetime.now()
    # Find the next minute that is a multiple of 5 (e.g., 30, 35, 40, ...)
    next_minute = ((now.minute // 5) + 1) * 5
    hour = now.hour + (next_minute // 60)
    next_minute %= 60
    hour %= 24
    # Set seconds to 30
    next_t = now.replace(hour=hour, minute=next_minute, second=30, microsecond=0)
    # If the next time is in the past (i.e., it's already xx:yy:30), add 5 minutes
    if next_t <= now:
        next_t = next_t.replace(minute=(next_t.minute + 5) % 60)
        if next_t.minute < now.minute:
            next_t = next_t.replace(hour=(next_t.hour + 1) % 24)
    return (next_t - now).total_seconds()

async def check_stock_once(check_at=None):
    url = "https://growagarden.gg/api/stock"
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url)
            resp.raise_for_status()
            data = await resp.json()

        watchlist = load_watchlist()
        if not watchlist:
            print("⚠️ Watchlist is empty.")
            return

        current = {}
        # categories that have ‘value’
        for cat in ("gearStock", "seedsStock", "cosmeticsStock", "eggStock", "merchantsStock",
                    "easterStock", "nightStock", "eventStock"):
            items = combine_items(data.get(cat, []))
            for it in items:
                current[it["name"]] = it["quantity"]

        message = f"📦 Stock check at {check_at}:\n"

        for name in watchlist:
            qty = current.get(name, 0)
            if qty > 0:
                message += f"*{name}*: {qty}\n"

        if message.strip() == f"📦 Stock check at {check_at}:":
            print("📦 No items in stock from watchlist.")
            return
        
        print(message.strip())
        await send_telegram_notification(message.strip())
        previous_stock.update(current)

    except Exception as e:
        print(f"❌ Fetch error: {e}")
        await send_telegram_notification(f"Error fetching stock: {e}")

async def main_loop():
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"⏰ Check at {now}")
        await check_stock_once(check_at=now)
        wait = seconds_until_next_5_min_offset_1()
        print(f"🕒 Sleep for {int(wait)} s")
        await asyncio.sleep(wait)

if __name__ == "__main__":
    asyncio.run(main_loop())
