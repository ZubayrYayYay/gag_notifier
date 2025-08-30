package main

import (
	"database/sql"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
	_ "github.com/mattn/go-sqlite3"
	"gopkg.in/telebot.v3"
)

var inlineMenu = &telebot.ReplyMarkup{}

var btnAddWatchlist = inlineMenu.Data("Add Item to Watchlist", "add_watchlist_btn")
var btnRemoveWatchlist = inlineMenu.Data("Remove Item from Watchlist", "remove_watchlist_btn")
var btnViewWatchlist = inlineMenu.Data("View Watchlist", "view_watchlist_btn")
var btnAddItem = inlineMenu.Data("Add an Item", "add_item_btn")
var btnRemoveItem = inlineMenu.Data("Remove an Item", "remove_item_btn")
var btnEnableNoti = inlineMenu.Data("Enable Notifications", "enable_noti_btn")
var btnDisableNoti = inlineMenu.Data("Disable Notifications", "disable_noti_btn")
var btnCancel = inlineMenu.Data("Cancel", "cancel_btn")

func main() {
	err := godotenv.Load()
	if err != nil {
		log.Fatal(err)
	}

	db, err := sql.Open("sqlite3", "./gag_notifier.db")
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	createItemsTable(db)
	createUsersTable(db)
	createWatchlistTable(db)

	pref := telebot.Settings{
		Token:  os.Getenv("TELEGRAM_BOT_TOKEN"),
		Poller: &telebot.LongPoller{Timeout: 10 * time.Second},
	}

	b, err := telebot.NewBot(pref)
	if err != nil {
		log.Fatal(err)
	}

	b.Handle("/start", func(c telebot.Context) error {
		return start(c, db, inlineMenu)
	})

	b.Handle(telebot.OnCallback, func(c telebot.Context) error {
		return handleCallback(c, db)
	})

	b.Handle(telebot.OnText, func(c telebot.Context) error {
		return handleText(c, db)
	})

	log.Println("Bot started with polling...")
	b.Start()
}

func createItemsTable(db *sql.DB) {
	sqlStmt := `
	CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
	`
	_, err := db.Exec(sqlStmt)
	if err != nil {
		log.Fatal(err)
	}
}

func createUsersTable(db *sql.DB) {
	sqlStmt := `
	CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT, is_notified INTEGER DEFAULT 1);
	`
	_, err := db.Exec(sqlStmt)
	if err != nil {
		log.Fatal(err)
	}
}

func createWatchlistTable(db *sql.DB) {
	sqlStmt := `
	CREATE TABLE IF NOT EXISTS watchlist (user_id TEXT, item_id INTEGER, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(item_id) REFERENCES items(id));
	`
	_, err := db.Exec(sqlStmt)
	if err != nil {
		log.Fatal(err)
	}
}

func start(c telebot.Context, db *sql.DB, inlineMenu *telebot.ReplyMarkup) error {
	user := c.Sender()
	// Insert user into the database if not exists
	_, err := db.Exec(
		`INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)`,
		user.ID, user.Username,
	)
	if err != nil {
		return c.Send("Failed to register user.")
	}

	var isNotified int
	err = db.QueryRow("SELECT is_notified FROM users WHERE id = ?", user.ID).Scan(&isNotified)
	if err != nil {
		return c.Send("Failed to retrieve user notification settings.")
	}

	rows := []telebot.Row{
		{btnAddWatchlist},
		{btnRemoveWatchlist},
		{btnViewWatchlist},
	}

	if isNotified == 0 {
		rows = append(rows, telebot.Row{btnEnableNoti})
	} else {
		rows = append(rows, telebot.Row{btnDisableNoti})
	}

	admin_id, err := strconv.ParseInt(os.Getenv("TELEGRAM_ADMIN_CHAT_ID"), 10, 64)
	if err != nil {
		log.Fatal(err)
	}

	if user.ID == admin_id {
		rows = append(rows, telebot.Row{btnAddItem})
		rows = append(rows, telebot.Row{btnRemoveItem})
	}

	inlineMenu.Inline(rows...)

	return c.Send("Hello @"+user.Username+", you can now use the bot!", inlineMenu)
}

func btnAddWatchlistFunc(c telebot.Context) error {
	// Implementation for adding an item to the watchlist
	c.Set("add_watchlist", true)

	inlineMenu := &telebot.ReplyMarkup{}

	inlineMenu.Inline(
		telebot.Row{btnCancel},
	)

	return c.Send("Please send the item name to search the item:", inlineMenu)
}

func btnRemoveWatchlistFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for removing an item from the watchlist
	userItems, err := getWatchlistItems(c.Sender().ID, db)
	if err != nil {
		return c.Send("Failed to retrieve watchlist.")
	}

	rows := []telebot.Row{}
	inlineMenu := &telebot.ReplyMarkup{}
	for _, item := range userItems {
		btn := inlineMenu.Data(item, "remove_watchlist_"+item)
		rows = append(rows, telebot.Row{btn})
	}

	rows = append(rows, telebot.Row{btnCancel})

	inlineMenu.Inline(rows...)

	return c.Send("Please select an item to remove from your watchlist:", inlineMenu)
}

func btnAddItemFunc(c telebot.Context) error {
	// Implementation for adding an item to the database
	c.Set("add_item", true)

	inlineMenu := &telebot.ReplyMarkup{}

	// Add buttons to the inline menu
	inlineMenu.Inline(
		telebot.Row{btnCancel},
	)

	return c.Send("Please send the item name to add it to the database:", inlineMenu)
}

func btnRemoveItemFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for removing an item from the database
	c.Set("remove_item", true)

	inlineMenu := &telebot.ReplyMarkup{}

	// Add buttons to the inline menu
	inlineMenu.Inline(
		telebot.Row{btnCancel},
	)

	rows, err := db.Query("SELECT name FROM items")
	if err != nil {
		return c.Send("Failed to retrieve items.")
	}
	defer rows.Close()

	var items []string
	for rows.Next() {
		var item string
		if err := rows.Scan(&item); err != nil {
			return c.Send("Failed to scan item.")
		}
		items = append(items, item)
	}

	itemList := ""
	for i, item := range items {
		itemList += fmt.Sprintf("%d. %s\n", i+1, item)
	}

	return c.Send("Please send the item name to remove it from the database:\n\n"+itemList, inlineMenu)
}

func btnViewWatchlistFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for viewing the watchlist
	return nil
}

func btnEnableNotiFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for enabling notifications
	return nil
}

func btnDisableNotiFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for disabling notifications
	return nil
}

func btnCancelFunc(c telebot.Context, db *sql.DB) error {
	// Implementation for canceling the current action
	return nil
}

func searchItemsLike(query string, db *sql.DB) ([]string, error) {
	rows, err := db.Query(`SELECT name FROM items WHERE name LIKE ?`, "%"+query+"%")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		results = append(results, name)
	}
	return results, nil
}

func insertItem(item string, db *sql.DB) error {
	_, err := db.Exec(`INSERT INTO items (name) VALUES (?)`, item)
	return err
}

func deleteItem(item string, db *sql.DB) error {
	_, err := db.Exec(`DELETE FROM items WHERE name = ?`, item)
	return err
}

func getWatchlistItems(userID int64, db *sql.DB) ([]string, error) {
	rows, err := db.Query(`SELECT item_name FROM watchlist WHERE user_id = ?`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var items []string
	for rows.Next() {
		var item string
		if err := rows.Scan(&item); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, nil
}

func insertWatchlistItem(item string, userID int64, db *sql.DB) error {
	_, err := db.Exec(`INSERT INTO watchlist (user_id, item_name) VALUES (?, ?)`, userID, item)
	return err
}

func deleteWatchlistItem(item string, userID int64, db *sql.DB) error {
	_, err := db.Exec(`DELETE FROM watchlist WHERE user_id = ? AND item_name = ?`, userID, item)
	return err
}

func handleText(c telebot.Context, db *sql.DB) error {
	if c.Get("add_item") != nil {
		err := insertItem(c.Text(), db)
		if err != nil {
			return c.Send("Failed to add item.", inlineMenu)
		}
		return c.Send("Item added successfully.", inlineMenu)
	}

	if c.Get("remove_item") != nil {
		err := deleteItem(c.Text(), db)
		if err != nil {
			return c.Send("Failed to remove item.", inlineMenu)
		}
		return c.Send("Item removed successfully.", inlineMenu)
	}

	if c.Get("add_watchlist") != nil {
		results, err := searchItemsLike(c.Text(), db)
		if err != nil {
			return c.Send("Failed to search items.", inlineMenu)
		}
		if len(results) == 0 {
			return c.Send("No matching items found.", inlineMenu)
		}

		btnRows := []telebot.Row{}
		inlineMenu := &telebot.ReplyMarkup{}

		for _, item := range results {
			btn := inlineMenu.Data(item, "add_watchlist_"+item)
			btnRows = append(btnRows, telebot.Row{btn})
		}

		btnRows = append(btnRows, telebot.Row{btnCancel})

		// Add buttons to the inline menu
		inlineMenu.Inline(btnRows...)

		return c.Send("List item(s) found in watchlist:", inlineMenu)
	}

	return c.Send("Please use the buttons to interact with the bot.", inlineMenu)
}

func handleCallback(c telebot.Context, db *sql.DB) error {
	// Handle callback queries
	callback := c.Callback()
	switch {
	case strings.HasPrefix(callback.Data, "add_watchlist_"):
		item := strings.TrimPrefix(callback.Data, "add_watchlist_")
		// Add item to watchlist
		err := insertWatchlistItem(item, c.Sender().ID, db)
		if err != nil {
			return c.Send("Failed to add item to watchlist.")
		}
		return c.Send("Item added to watchlist.", inlineMenu)
	case strings.HasPrefix(callback.Unique, "remove_watchlist_"):
		item := strings.TrimPrefix(callback.Unique, "remove_watchlist_")
		// Remove item from watchlist
		err := deleteWatchlistItem(item, c.Sender().ID, db)
		if err != nil {
			return c.Send("Failed to remove item from watchlist.")
		}
		return c.Send("Item removed from watchlist.", inlineMenu)
	}

	switch callback.Unique {
	case "add_watchlist_btn":
		return btnAddWatchlistFunc(c)
	case "remove_watchlist_btn":
		return btnRemoveWatchlistFunc(c, db)
	case "view_watchlist_btn":
		return btnViewWatchlistFunc(c, db)
	case "cancel_btn":
		return btnCancelFunc(c, db)
	case "add_item_btn":
		return btnAddItemFunc(c)
	case "remove_item_btn":
		return btnRemoveItemFunc(c, db)
		// case "enable_noti_btn":
		// 	return btnEnableNotificationFunc(c, db)
		// case "disable_noti_btn":
		// 	return btnDisableNotificationFunc(c, db)
	}
	return c.Send("Unknown action.", inlineMenu)
}
