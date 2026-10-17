import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import os
import tempfile
from urllib.parse import urlparse
from datetime import datetime

# ================= Configuration =================
BOT_TOKEN = "8430154368:AAFvGXAgbpcn0CQII2X-CcsIeyQIEXMlbG4"
ADMIN_ID = 8725461956
ADMIN_CHANNEL_ID = "@thelitegiveaway"  

bot = telebot.TeleBot(BOT_TOKEN)

try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"Error fetching bot username: {e}")
    BOT_USERNAME = "YourBotUsername"

# ================= Database Setup =================
DB_PATH = os.path.abspath("bot_database.db")
BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "database_backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
db_lock = threading.RLock()


def backup_database(label="auto"):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"bot_database_{label}_{stamp}.db")
    try:
        with db_lock:
            conn.commit()
            backup_conn = sqlite3.connect(backup_path)
            try:
                conn.backup(backup_conn)
                backup_conn.commit()
            finally:
                backup_conn.close()
        return backup_path
    except Exception as exc:
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except OSError:
            pass
        return None

def automatic_backup_loop():
    while True:
        backup_path = backup_database("auto")
        if backup_path:
            try:
                with open(backup_path, "rb") as backup_file:
                    bot.send_document(
                        ADMIN_ID,
                        backup_file,
                        caption=(f"🗄️ Automatic DB backup\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    )
            except Exception:
                pass
        time.sleep(2 * 60 * 60)

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    total_invites INTEGER DEFAULT 0,
    total_withdrawals INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL
)''')

try:
    cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
    conn.commit()
except sqlite3.OperationalError:
    pass

cursor.execute('''CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    reason TEXT,
    date TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    link TEXT
)''')
conn.commit()

# ================= Helper Functions =================

def add_user(user_id):
    with db_lock:
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            return True
        return False

def check_force_sub(user_id):
    with db_lock:
        cursor.execute("SELECT channel_id FROM channels")
        channels = cursor.fetchall()

    if not channels:
        return True

    for (ch_id,) in channels:
        try:
            status = bot.get_chat_member(ch_id, user_id).status
            if status not in ("creator", "administrator", "member", "restricted"):
                return False
        except Exception:
            return False
    return True

def require_force_sub(chat_id, user_id):
    if check_force_sub(user_id):
        return True
    bot.send_message(
        chat_id,
        "⚠️ **Action Required!**\n\nTo use this bot, join every official channel below, then tap '✅ I Have Joined'.",
        reply_markup=force_sub_keyboard(),
        parse_mode="Markdown"
    )
    return False

def get_welcome_text(user_name):
    return f"👋 **Welcome to the API Bot, {user_name}!** 🤖\n\nGet API access instantly. \n💰 Refer your friends to earn credits and unlock premium API access!\n\n👇 Select an option from the menu below:"

# ================= Keyboards =================
def main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💸 Invite & Earn", "👀 Profile", "📊 Bot Status", "📜 Invite History", "🔑 Get API", "⚠️ Help & Support")
    if user_id == ADMIN_ID:
        markup.add("🛠 Admin Panel")
    return markup

def force_sub_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    cursor.execute("SELECT channel_id, link FROM channels")
    for ch_id, link in cursor.fetchall():
        markup.add(InlineKeyboardButton("📢 Join Channel", url=link))
    markup.add(InlineKeyboardButton("✅ I Have Joined", callback_data="check_joined"))
    return markup

def api_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📱 Number Info", "🔎 Truecaller Info")
    markup.add("🪪 Aadhaar Info", "💰 IMEI Info")
    markup.add("🚗 Challan Info", "💳 PAN Card Info")
    markup.add("🏢 GST Info", "📍 Pincode Info")
    markup.add("🌐 IP Info", "🏍️ Vehicle Info")
    markup.add("🚘 RC Info", "📸 Instagram Info")
    markup.add("👻 Snapchat Info", "🇵🇰 Pakistan Info")
    markup.add("📧 Email info", "🔗 Number → Instagram")
    markup.add("📧 Email → Instagram", "📸 Instagram → Number")
    markup.add("🪪 Addhar →family", "🔙 Back")
    return markup

valid_apis = [
    "📱 Number Info", "🔎 Truecaller Info", "🪪 Aadhaar Info", "💰 IMEI Info",
    "🚗 Challan Info", "💳 PAN Card Info", "🏢 GST Info", "📍 Pincode Info",
    "🌐 IP Info", "🏍️ Vehicle Info", "🚘 RC Info", "📸 Instagram Info",
    "👻 Snapchat Info", "🇵🇰 Pakistan Info", "📧 Email info",
    "🔗 Number → Instagram", "📧 Email → Instagram", "📸 Instagram → Number",
    "🪪 Addhar →family"
]

pending_withdrawals = {}

# ================= Handlers =================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    args = message.text.split()
    
    is_new = add_user(user_id)
    if is_new and len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            with db_lock:
                cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                conn.commit()

    if not require_force_sub(message.chat.id, user_id):
        return

    bot.send_message(message.chat.id, get_welcome_text(message.from_user.first_name), reply_markup=main_menu(user_id), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "check_joined")
def check_joined_callback(call):
    user_id = call.from_user.id
    if check_force_sub(user_id):
        with db_lock:
            cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row[0]:
                referrer_id = row[0]
                cursor.execute("UPDATE users SET balance = balance + 1, total_invites = total_invites + 1 WHERE user_id = ?", (referrer_id,))
                
                reason = f"Referral: {call.from_user.first_name} joined & verified"
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("INSERT INTO history (user_id, amount, reason, date) VALUES (?, 1, ?, ?)", (referrer_id, reason, date_str))
                cursor.execute("UPDATE users SET referred_by = NULL WHERE user_id = ?", (user_id,))
                conn.commit()
                
                # Yahan Referral Notification Fix Kiya Gaya Hai
                joined_username = f"@{call.from_user.username}" if call.from_user.username else "No Username"
                notification_text = (
                    f"🎉 **New Referral Verified!**\n\n"
                    f"👤 **Name:** {call.from_user.first_name}\n"
                    f"🔗 **Username:** {joined_username}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💰 **Reward:** +1 Credit added to your balance!"
                )
                try: bot.send_message(referrer_id, notification_text, parse_mode="Markdown")
                except: pass

        bot.answer_callback_query(call.id, "✅ Subscription verified!")
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        bot.send_message(call.message.chat.id, get_welcome_text(call.from_user.first_name), reply_markup=main_menu(user_id), parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined all channels yet! Please join first.", show_alert=True)

@bot.message_handler(func=lambda message: message.text == "💸 Invite & Earn")
def invite_earn(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    text = f"💎 Per Refer Reward\n━━━━━━━━━━━━━━━\n💰 Earn 1 credit Per Referral\n━━━━━━━━━━━━━━━\n🔗 Your Referral Link:\n{ref_link}\n━━━━━━━━━━━━━━━\n✅ Share With Friends & Earn Easily!"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔗 Share Link", url=f"https://t.me/share/url?url={ref_link}"), InlineKeyboardButton("👥 My Invites", callback_data="my_invites"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_menu"))
    bot.send_message(message.chat.id, text, reply_markup=markup, disable_web_page_preview=True)

@bot.message_handler(func=lambda message: message.text == "👀 Profile")
def profile(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    cursor.execute("SELECT balance, total_invites, total_withdrawals FROM users WHERE user_id = ?", (message.from_user.id,))
    bal, inv, withdr = cursor.fetchone()
    bot.send_message(message.chat.id, f"👀 Profile\n\n🔗 User ID: `{message.from_user.id}`\n👉 Total Invite: {inv}\n💰 Current Balance: {bal}\n💵 Total Withdrawal: {withdr}", parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "📊 Bot Status")
def bot_status(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    msg = bot.send_message(message.chat.id, "Processing... ⏳")
    time.sleep(1) 
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    bot.edit_message_text(f"📊 Bot Status Panel\n━━━━━━━━━━━━━━━\n🤖 Status ▸ Online\n⚡ Performance ▸ Excellent\n👥 Total Users ▸ {users}\n━━━━━━━━━━━━━━━\n✅ All Services Are Running Good.", chat_id=message.chat.id, message_id=msg.message_id)

@bot.message_handler(func=lambda message: message.text == "📜 Invite History")
def invite_history(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    cursor.execute("SELECT amount, reason, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "No history found.")
        return
    text = f"⭐ Star History ({len(rows)} recent records)\n\n"
    for amt, reason, date in rows:
        text += f"⭐ +{amt} — {reason}\n📅 {date}\n\n" if amt > 0 else f"⭐ {amt} — {reason}\n📅 {date}\n\n"
    bot.send_message(message.chat.id, text)

# ================= NAYA API WITHDRAWAL LOGIC =================

@bot.message_handler(func=lambda message: message.text == "🔑 Get API")
def get_api(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    user_id = message.from_user.id
    
    with db_lock:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]
    
    if balance < 5:
        text = f"⚠️ Minimum Balance Required\n━━━━━━━━━━━━━━━\n💰 Your Balance: {balance} credits\n✅ Minimum Required: 5 credits\n\n👀 Make More Refers To Earn More Balance"
        bot.send_message(message.chat.id, text)
    else:
        msg = bot.send_message(
            message.chat.id, 
            f"💰 **Your Balance:** {balance} credits\n\n"
            f"⚙️ **API Pricing:** 2 Credits = 1 Day\n"
            f"⚠️ **Minimum Withdrawal:** 5 Credits\n\n"
            f"👇 **Kitne credit use karna chahte ho? Sirf number type karke bhejo:**\n*(Jaise: 10, 20, 50)*", 
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, process_api_amount)

def process_api_amount(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    user_id = message.from_user.id
    
    if message.text == "🔙 Back":
        back_to_main(message)
        return

    if not message.text.isdigit():
        msg = bot.send_message(message.chat.id, "❌ Sirf number type karo (Jaise: 10, 50). Wapas type karke bhejo:")
        bot.register_next_step_handler(msg, process_api_amount)
        return
        
    amount = int(message.text)
    
    with db_lock:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]

    if amount < 5:
        msg = bot.send_message(message.chat.id, "❌ Minimum 5 credits nikalna zaroori hai. Wapas amount type karo:")
        bot.register_next_step_handler(msg, process_api_amount)
        return
        
    if amount > balance:
        msg = bot.send_message(message.chat.id, f"❌ Aapke paas itne credits nahi hain.\n💰 Your Balance: {balance}\nWapas sahi amount type karo:")
        bot.register_next_step_handler(msg, process_api_amount)
        return
        
    days = amount / 2
    days_text = f"{int(days)}" if days.is_integer() else f"{days}"
    
    pending_withdrawals[user_id] = {'amount': amount, 'days': days_text}
    
    bot.send_message(
        message.chat.id, 
        f"✅ **Credits Entered:** {amount}\n"
        f"⏳ **Validity:** {days_text} Days API\n\n"
        f"👇 **Ab niche menu se apna API select karo jo tumhe chahiye:**", 
        reply_markup=api_menu(), 
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda message: message.text in valid_apis)
def process_api_button(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    user_id = message.from_user.id
    
    if user_id not in pending_withdrawals:
        bot.send_message(message.chat.id, "❌ Pehle '🔑 Get API' par click karke credit amount type karo.", reply_markup=main_menu(user_id))
        return
        
    request_text = message.text.strip()
    data = pending_withdrawals.pop(user_id) 
    amount = data['amount']
    days = data['days']
    
    with db_lock:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]
        
        if balance < amount:
            bot.send_message(message.chat.id, f"❌ Transaction failed. Not enough credits.")
            return

        cursor.execute("UPDATE users SET balance = balance - ?, total_withdrawals = total_withdrawals + ? WHERE user_id = ?", (amount, amount, user_id))
        cursor.execute("INSERT INTO history (user_id, amount, reason, date) VALUES (?, ?, ?, ?)", (user_id, -amount, f"API Request: {request_text} ({days} days)", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        history_id = cursor.lastrowid
        conn.commit()

    # Yahan Username Fix Kiya Gaya Hai
    username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    admin_text = (
        f"🆕 **NEW API WITHDRAWAL REQUEST**\n\n"
        f"👤 **Name:** {message.from_user.first_name}\n"
        f"🔗 **Username:** {username}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"💰 **Credits Used:** {amount}\n"
        f"⏳ **Validity Requested:** {days} Days\n"
        f"🎯 **Requested API:** {request_text}\n"
        f"🕒 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"⚙️ **Action:** Please message the user to provide API."
    )
    
    try:
        bot.send_message(ADMIN_CHANNEL_ID, admin_text, parse_mode="Markdown")
        bot.send_message(
            message.chat.id, 
            f"✅ **Request Sent Successfully!**\n\n"
            f"🎯 **API:** {request_text}\n"
            f"💰 **Credits Deducted:** {amount}\n"
            f"⏳ **Validity:** {days} Days\n\n"
            f"Admin aapko jaldi hi message karke access de denge.", 
            reply_markup=main_menu(user_id),
            parse_mode="Markdown"
        )
    except Exception:
        with db_lock:
            cursor.execute("UPDATE users SET balance = balance + ?, total_withdrawals = total_withdrawals - ? WHERE user_id = ?", (amount, amount, user_id))
            cursor.execute("DELETE FROM history WHERE id = ?", (history_id,))
            conn.commit()
        bot.send_message(message.chat.id, "⚠️ Request failed to send. Check channel permissions. Credits refunded.", reply_markup=main_menu(user_id))


@bot.message_handler(func=lambda message: message.text == "🔙 Back")
def back_to_main(message):
    if not require_force_sub(message.chat.id, message.from_user.id): return
    if message.from_user.id in pending_withdrawals:
        del pending_withdrawals[message.from_user.id]
    bot.send_message(message.chat.id, "🔙 Main Menu", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "⚠️ Help & Support")
def help_support(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Contact Support", url="https://t.me/Aditya_dark0"))
    bot.send_message(message.chat.id, "⚠️ Help & Support\n\nKisi bhi problem ke liye contact karo:\n👀 Support: @Aditya_dark0", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["back_to_menu", "my_invites"])
def callback_handler(call):
    if not require_force_sub(call.message.chat.id, call.from_user.id): return
    if call.data == "back_to_menu":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, get_welcome_text(call.from_user.first_name), reply_markup=main_menu(call.from_user.id), parse_mode="Markdown")
    elif call.data == "my_invites":
        invite_history(call.message)
        bot.answer_callback_query(call.id)

# ================= Admin Panel =================
@bot.message_handler(func=lambda message: message.text == "🛠 Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("➕ Add Force Sub Channel", callback_data="admin_add_channel"),
        InlineKeyboardButton("⭐ Add Referral Credits", callback_data="admin_add_referral"),
        InlineKeyboardButton("📥 Load Database", callback_data="admin_load_database"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
    )
    bot.send_message(message.chat.id, "🛠 Admin Panel:\nSelect an option below:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_ID: return
    if call.data == "admin_add_channel":
        msg = bot.send_message(call.message.chat.id, "Send the Public Channel Username or Link.")
        bot.register_next_step_handler(msg, process_add_channel)
    elif call.data == "admin_add_referral":
        msg = bot.send_message(call.message.chat.id, "⭐ Add Referral Credits\n\nSend the user's Telegram ID:")
        bot.register_next_step_handler(msg, process_referral_user_id)
    elif call.data == "admin_load_database":
        msg = bot.send_message(call.message.chat.id, "📥 Send the SQLite database file (.db, .sqlite, or .sqlite3).")
        bot.register_next_step_handler(msg, process_load_database_file)
    elif call.data == "admin_broadcast":
        msg = bot.send_message(call.message.chat.id, "Send the message you want to broadcast to all users:")
        bot.register_next_step_handler(msg, process_broadcast)

def process_referral_user_id(message):
    target_id = int(message.text.strip())
    msg = bot.send_message(message.chat.id, f"User ID: {target_id}\nNow send the number of referral credits to add:")
    bot.register_next_step_handler(msg, lambda m: process_referral_credit_amount(m, target_id))

def process_referral_credit_amount(message, target_id):
    amount = int(message.text.strip())
    with db_lock:
        cursor.execute("UPDATE users SET balance = balance + ?, total_invites = total_invites + ? WHERE user_id = ?", (amount, amount, target_id))
        cursor.execute("INSERT INTO history (user_id, amount, reason, date) VALUES (?, ?, ?, ?)", (target_id, amount, "Admin-added credits", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    bot.send_message(message.chat.id, f"✅ Added {amount} credits to user {target_id}.")

def process_add_channel(message):
    raw = message.text.strip()
    username = raw if raw.startswith("@") else None
    if not username:
        parsed = urlparse(raw if raw.startswith("http") else "https://" + raw)
        path = [p for p in parsed.path.split("/") if p]
        if path: username = "@" + path[0].split("?")[0]
    try:
        chat = bot.get_chat(username)
        link = f"https://t.me/{chat.username}"
        with db_lock:
            cursor.execute("INSERT OR REPLACE INTO channels (channel_id, link) VALUES (?, ?)", (str(chat.id), link))
            conn.commit()
        bot.send_message(message.chat.id, f"✅ Channel added!\n📢 {username}\n🔗 {link}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

def process_load_database_file(message):
    document = message.document
    file_info = bot.get_file(document.file_id)
    file_bytes = bot.download_file(file_info.file_path)
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    with os.fdopen(fd, "wb") as output:
        output.write(file_bytes)
    source_conn = sqlite3.connect(temp_path)
    with db_lock:
        conn.commit()
        source_conn.backup(conn)
        conn.commit()
    bot.send_message(message.chat.id, "✅ Database loaded successfully.")

def process_broadcast(message):
    cursor.execute("SELECT user_id FROM users")
    for (uid,) in cursor.fetchall():
        try:
            bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            time.sleep(0.05) 
        except: pass
    bot.send_message(message.chat.id, "✅ Broadcast finished.")

@bot.message_handler(func=lambda message: True)
def block_unsubbed_users(message):
    require_force_sub(message.chat.id, message.from_user.id)

# ================= Start Polling =================
if __name__ == "__main__":
    threading.Thread(target=automatic_backup_loop, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
