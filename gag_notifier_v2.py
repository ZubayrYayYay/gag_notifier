from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from dotenv import load_dotenv
from datetime import datetime, timedelta
from collections import defaultdict
import os
import sqlite3
import requests
import asyncio
import telegram

# Config
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ITEMS_PER_PAGE = 5
conn = sqlite3.connect('gag_notifier.db')

current_stock = {}
previous_stock = {}

# Create a table if it doesn't exist
conn.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
conn.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT, is_notified INTEGER DEFAULT 1)')
conn.execute('CREATE TABLE IF NOT EXISTS watchlist (user_id TEXT, item_id INTEGER, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(item_id) REFERENCES items(id))')
conn.commit()
conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conn = sqlite3.connect('gag_notifier.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)', (user.id, user.username))
    conn.commit()
    
    # Create inline keyboard
    keyboard = [
        [InlineKeyboardButton("Add Item to Watchlist", callback_data='btn_add')],
        [InlineKeyboardButton("Remove Item from Watchlist", callback_data='btn_remove')],
        [InlineKeyboardButton("View Watchlist", callback_data='view_watchlist')],
    ]

    cursor.execute('SELECT is_notified FROM users WHERE id = ?', (user.id,))
    is_notified = cursor.fetchone()
    if is_notified and is_notified[0] == 0:
        keyboard.append([InlineKeyboardButton("Enable Notifications", callback_data='enable_notifications')])
    else:
        keyboard.append([InlineKeyboardButton("Disable Notifications", callback_data='disable_notifications')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f'Hello @{user.first_name}, you can now use the bot!',
        reply_markup=reply_markup
    )

def get_keyboard(update: Update) -> InlineKeyboardMarkup:
    user = update.effective_user
    conn = sqlite3.connect('gag_notifier.db')
    cursor = conn.cursor()
    keyboard = [
        [InlineKeyboardButton("Add Item to Watchlist", callback_data='btn_add')],
        [InlineKeyboardButton("Remove Item from Watchlist", callback_data='btn_remove')],
        [InlineKeyboardButton("View Watchlist", callback_data='view_watchlist')],
    ]
    cursor.execute('SELECT is_notified FROM users WHERE id = ?', (user.id,))
    is_notified = cursor.fetchone()
    if is_notified and is_notified[0] == 0:
        keyboard.append([InlineKeyboardButton("Enable Notifications", callback_data='enable_notifications')])
    else:
        keyboard.append([InlineKeyboardButton("Disable Notifications", callback_data='disable_notifications')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup

def set_notification_status(user_id: int, status: int):
    conn = sqlite3.connect('gag_notifier.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_notified = ? WHERE id = ?', (status, user_id))
    conn.commit()
    conn.close()

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    update_items()
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Get current page from context, default to 0
    page = context.user_data.get('items_page', 0)

    if query.data == 'btn_add' or query.data.startswith('page_'):
        set_notification_status(user_id, 0)  # Disable notifications for adding items
        # If navigating, update page
        if query.data.startswith('page_'):
            page = int(query.data.split('_')[1])
            context.user_data['items_page'] = page
        else:
            page = 0
            context.user_data['items_page'] = page

        # Fetch items from DB
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM items ORDER BY name ASC')
        items = [item[0] for item in cursor.fetchall()]
        conn.close()

        # Pagination logic
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = items[start_idx:end_idx]

        keyboard = []
        # Add "Add Manually" at the top
        keyboard.append([InlineKeyboardButton("➕ Add Manually", callback_data='add_manual')])
        # Add item buttons
        for item_name in page_items:
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f'item_{item_name}')])

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⏮️ First", callback_data='page_0'))
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f'page_{page-1}'))
        if end_idx < len(items):
            last_page = (len(items) - 1) // ITEMS_PER_PAGE
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f'page_{page+1}'))
            nav_buttons.append(InlineKeyboardButton("⏭️ Last", callback_data=f'page_{last_page}'))
        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("Cancel", callback_data='btn_cancel')])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="Choose an item to add to your watchlist or add manually:",
            reply_markup=reply_markup
        )

    elif query.data == 'btn_cancel':
        set_notification_status(user_id, 1)  # Re-enable notifications
        context.user_data['awaiting_remove_item'] = False
        context.user_data['awaiting_manual_item'] = False
        await query.edit_message_text(text="Cancelled. Notifications re-enabled.", reply_markup=get_keyboard(update))

    elif query.data.startswith('item_'):
        item_name = query.data[5:]
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM items WHERE name = ?', (item_name,))
        item_row = cursor.fetchone()
        if item_row:
            item_id = item_row[0]
            set_notification_status(user_id, 1)  # Re-enable notifications after manual item handling
            if context.user_data.get('awaiting_remove_item'):
                cursor.execute('DELETE FROM watchlist WHERE user_id = ? AND item_id = ?', (str(user_id), item_id))
                if cursor.rowcount > 0:
                    await query.edit_message_text(text=f"✅ Removed '{item_name}' from your watchlist.", reply_markup=get_keyboard(update))
                else:
                    await query.edit_message_text(text=f"❌ '{item_name}' is not in your watchlist.", reply_markup=get_keyboard(update))
            else:
                cursor.execute('SELECT 1 FROM watchlist WHERE user_id = ? AND item_id = ?', (str(user_id), item_id))
                exists = cursor.fetchone()
                if exists:
                    await query.edit_message_text(text=f"⚠️ '{item_name}' is already in your watchlist.", reply_markup=get_keyboard(update))
                else:
                    cursor.execute('INSERT OR IGNORE INTO watchlist (user_id, item_id) VALUES (?, ?)', (str(user_id), item_id))
                    conn.commit()
                    await query.edit_message_text(text=f"✅ Added '{item_name}' to your watchlist.", reply_markup=get_keyboard(update))
        else:
            await query.edit_message_text(text="❌ Item not found.", reply_markup=get_keyboard(update))
        conn.close()
        context.user_data['items_page'] = 0  # Reset page

    elif query.data == 'add_manual':
        context.user_data['awaiting_manual_item'] = True
        await query.edit_message_text(text="Please send the item name you want to add(e.g. Grandmaster Sprinkler OR Grandmaster Sprinkler,Beanstalk ):", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data='btn_cancel')]
        ]))
        context.user_data['items_page'] = 0  # Reset page
    
    elif query.data == 'remove_manual':
        context.user_data['awaiting_remove_item'] = True
        await query.edit_message_text(text="Please send the item name you want to remove(e.g. Grandmaster Sprinkler OR Grandmaster Sprinkler,Beanstalk ):", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data='btn_cancel')]
        ]))
        context.user_data['items_page'] = 0  # Reset page

    elif query.data == 'btn_remove' or query.data.startswith('page_'):
        set_notification_status(user_id, 0)  # Disable notifications for removing items
        context.user_data['awaiting_remove_item'] = True
        # If navigating, update page
        if query.data.startswith('page_'):
            page = int(query.data.split('_')[1])
            context.user_data['items_page'] = page
        else:
            page = 0
            context.user_data['items_page'] = page

        # Fetch items from DB
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM items ORDER BY name ASC')
        items = [item[0] for item in cursor.fetchall()]
        conn.close()

        # Pagination logic
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = items[start_idx:end_idx]

        keyboard = []
        # Add "Remove Manually" at the top
        keyboard.append([InlineKeyboardButton("➖ Remove Manually", callback_data='remove_manual')])
        # Add item buttons
        for item_name in page_items:
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f'item_{item_name}')])

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⏮️ First", callback_data='page_0'))
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f'page_{page-1}'))
        if end_idx < len(items):
            last_page = (len(items) - 1) // ITEMS_PER_PAGE
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f'page_{page+1}'))
            nav_buttons.append(InlineKeyboardButton("⏭️ Last", callback_data=f'page_{last_page}'))
        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("Cancel", callback_data='btn_cancel')])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="Choose an item to REMOVE from your watchlist or remove manually:",
            reply_markup=reply_markup
        )
    elif query.data == 'view_watchlist':
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('SELECT items.name FROM watchlist JOIN items ON watchlist.item_id = items.id WHERE watchlist.user_id = ?', (str(user_id),))
        watchlist_items = cursor.fetchall()
        conn.close()
        if watchlist_items:
            watchlist_text = "Your Watchlist:\n" + "\n".join(item[0] for item in watchlist_items)
            await query.edit_message_text(text=watchlist_text, reply_markup=get_keyboard(update))
        else:
            await query.edit_message_text(text="Your watchlist is empty.", reply_markup=get_keyboard(update))
    elif query.data == 'enable_notifications':
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_notified = 1 WHERE id = ?', (str(user_id),))
        conn.commit()
        conn.close()
        await query.edit_message_text(text="Notifications enabled. You will now receive stock updates.", reply_markup=get_keyboard(update))
    elif query.data == 'disable_notifications':
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_notified = 0 WHERE id = ?', (str(user_id),))
        conn.commit()
        conn.close()
        await query.edit_message_text(text="Notifications disabled. You will no longer receive stock updates.", reply_markup=get_keyboard(update))
    else:
        await query.edit_message_text(text="Unknown action.", reply_markup=get_keyboard(update))

async def manual_item_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    item_names = [name.strip() for name in update.message.text.split(',')]
    if context.user_data.get('awaiting_manual_item'):
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        set_notification_status(user_id, 1)  # Re-enable notifications after manual item handling
        added = []
        already = []
        failed = []
        for item_name in item_names:
            if not item_name:
                continue
            cursor.execute('INSERT OR IGNORE INTO items (name) VALUES (?)', (item_name,))
            cursor.execute('SELECT id FROM items WHERE name = ?', (item_name,))
            item_row = cursor.fetchone()
            if item_row:
                item_id = item_row[0]
                cursor.execute('SELECT 1 FROM watchlist WHERE user_id = ? AND item_id = ?', (str(user_id), item_id))
                exists = cursor.fetchone()
                if exists:
                    already.append(item_name)
                else:
                    cursor.execute('INSERT INTO watchlist (user_id, item_id) VALUES (?, ?)', (str(user_id), item_id))
                    added.append(item_name)
            else:
                failed.append(item_name)
        conn.commit()
        conn.close()
        msg = ""
        if added:
            msg += f"✅ Added: {', '.join(added)}\n"
        if already:
            msg += f"⚠️ Already in watchlist: {', '.join(already)}\n"
        if failed:
            msg += f"❌ Failed to add: {', '.join(failed)}\n"
        await update.message.reply_text(msg.strip(), reply_markup=get_keyboard(update))
        context.user_data['awaiting_manual_item'] = False
    if context.user_data.get('awaiting_remove_item'):
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        set_notification_status(user_id, 1)  # Re-enable notifications after manual item handling
        removed = []
        not_in_watchlist = []
        not_found = []
        for item_name in item_names:
            if not item_name:
                continue
            cursor.execute('SELECT id FROM items WHERE name = ?', (item_name,))
            item_row = cursor.fetchone()
            if item_row:
                item_id = item_row[0]
                cursor.execute('DELETE FROM watchlist WHERE user_id = ? AND item_id = ?', (str(user_id), item_id))
                conn.commit()
                if cursor.rowcount > 0:
                    removed.append(item_name)
                else:
                    not_in_watchlist.append(item_name)
            else:
                not_found.append(item_name)
        conn.close()
        msg = ""
        if removed:
            msg += f"✅ Removed: {', '.join(removed)}\n"
        if not_in_watchlist:
            msg += f"❌ Not in watchlist: {', '.join(not_in_watchlist)}\n"
        if not_found:
            msg += f"❌ Item not found: {', '.join(not_found)}\n"
        await update.message.reply_text(msg.strip(), reply_markup=get_keyboard(update))
        context.user_data['awaiting_remove_item'] = False

def update_items():
    url = "https://growagarden.gg/api/stock"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json().get("lastSeen", [])
        items_exists = [item for item in data if item.get("seen") is not None]
        items_not_exists = [item for item in data if item.get("seen") is None]
        conn = sqlite3.connect('gag_notifier.db')
        cursor = conn.cursor()
        for item in items_exists:
            cursor.execute('INSERT OR IGNORE INTO items (name) VALUES (?)', (item["name"],))
        for item in items_not_exists:
            cursor.execute('DELETE FROM items WHERE name = ?', (item["name"],))
        conn.commit()
        conn.close()
    except requests.RequestException as e:
        print(f"❌ Failed to update items: {e}")
        # Optionally, you can log this error to a file or database for further analysis

def combine_items(items, key_qty="value"):
    d = defaultdict(int)
    for item in items:
        name = item.get("name")
        qty = item.get(key_qty, 0) or 0
        d[name] += qty
    return [{"name": name, "quantity": qty} for name, qty in d.items()]

def seconds_until_next_5_min_offset_1():
    now = datetime.now()
    # Find the next minute that is a multiple of 5 plus 1
    minute = ((now.minute // 5) + 1) * 5 + 1
    hour = now.hour
    if minute >= 60:
        minute -= 60
        hour += 1
        if hour >= 24:
            hour = 0
            now = now + timedelta(days=1)
    next_t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (next_t - now).total_seconds()
    if delta <= 0:
        next_t += timedelta(minutes=5)
        delta = (next_t - now).total_seconds()
    return delta

async def check_current_stock(check_at=None, app=None):
    global previous_stock
    url = "https://growagarden.gg/api/stock"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = {}
        for cat in ("gearStock", "seedsStock", "cosmeticsStock", "eggStock", "merchantsStock",
                    "easterStock", "nightStock", "eventStock"):
            items = combine_items(data.get(cat, []))
            for it in items:
                current[it["name"]] = it["quantity"]

        in_stock_items = [name for name, qty in current.items() if qty > 0]

        # Notify users
        if in_stock_items and app is not None:
            conn = sqlite3.connect('gag_notifier.db')
            cursor = conn.cursor()
            # Get all users who want notifications
            cursor.execute('SELECT id FROM users WHERE is_notified = 1')
            user_ids = [row[0] for row in cursor.fetchall()]
            for user_id in user_ids:
                # Get user's watchlist items that are in stock
                cursor.execute('''
                    SELECT items.name FROM watchlist
                    JOIN items ON watchlist.item_id = items.id
                    WHERE watchlist.user_id = ? AND items.name IN ({})
                '''.format(','.join('?' * len(in_stock_items))),
                [str(user_id)] + in_stock_items)
                watched_in_stock = [row[0] for row in cursor.fetchall()]
                if watched_in_stock:
                    message = f"📦 Stock check at {check_at}:\n"
                    for item_name in watched_in_stock:
                        message += f"*{item_name}*: {current[item_name]}\n"
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Add Item to Watchlist", callback_data='btn_add')],
                            [InlineKeyboardButton("Remove Item from Watchlist", callback_data='btn_remove')],
                            [InlineKeyboardButton("View Watchlist", callback_data='view_watchlist')],
                            [InlineKeyboardButton("Disable Notifications", callback_data='disable_notifications')]
                        ])
                    )
                else:
                    print(f"🗑️ No watched items in stock for user {user_id} at {check_at}")
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"No watched items in stock at {check_at}.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Add Item to Watchlist", callback_data='btn_add')],
                            [InlineKeyboardButton("Remove Item from Watchlist", callback_data='btn_remove')],
                            [InlineKeyboardButton("View Watchlist", callback_data='view_watchlist')],
                            [InlineKeyboardButton("Disable Notifications", callback_data='disable_notifications')]
                        ])
                    )
            conn.close()

        previous_stock = current.copy()
        current_stock.update(current)

    except Exception as e:
        print(f"❌ Fetch error: {e}")
        await app.bot.send_message(
            chat_id=os.getenv("TELEGRAM_ERROR_CHAT_ID"),
            text=f"❌ Error fetching stock data: {e}"
        )

async def periodic_stock_check(app):
    try:
        while True:
            now = datetime.now().strftime("%H:%M:%S")
            print(f"⏰ Check at {now}")
            await check_current_stock(check_at=now, app=app)
            wait = seconds_until_next_5_min_offset_1()
            print(f"🕒 Sleep for {int(wait)} s")
            await asyncio.sleep(wait)
    except KeyboardInterrupt:
        print("🔴 Stopping the notifier.")
    except Exception as e:
        print(f"❌ Fetch error: {e}")
        error_chat_id = os.getenv("TELEGRAM_ERROR_CHAT_ID")
        # Only try to send error message if chat_id is set and error is not Forbidden
        if error_chat_id and not isinstance(e, telegram.error.Forbidden):
            try:
                await app.bot.send_message(
                    chat_id=error_chat_id,
                    text=f"❌ Error fetching stock data: {e}"
                )
            except telegram.error.BadRequest as be:
                print(f"❌ Failed to send error message: {be}")

async def on_startup(app):
    app.create_task(periodic_stock_check(app))

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_item_handler))

app.post_init = on_startup  # Start background task after bot starts

app.run_polling()