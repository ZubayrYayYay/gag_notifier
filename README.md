## GAG Notifier

This is a Python script that monitors stock items from the GrowAGarden.gg API and sends Telegram notifications when items from your watchlist are in stock.

### Features
- Periodically checks stock for specific items.
- Sends notifications to a Telegram chat using a bot.
- Configurable watchlist and credentials via `.env` file.

### Requirements
- Python 3.7+
- See `requirements.txt` for dependencies.

### Setup
1. **Clone the repository or copy the files.**
2. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```
3. **Create a `.env` file** in the project directory with the following content:
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   ```
4. **Edit your watchlist:**
   - Add item names to `gag_watchlist.json` as a JSON array, e.g.:
     ```json
     ["Item1", "Item2", "Item3"]
     ```

### Usage
Run the script:
```
python gag_notifier.py
```

The script will check the stock every 5 minutes and notify you via Telegram if any watched items are available.

### Notes
- Make sure your Telegram bot is added to the chat and has permission to send messages.
- Keep your `.env` file secret and do not commit it to version control.

---
MIT License
