import io
import os
import random
import sqlite3
from collections import defaultdict
from telebot import TeleBot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "8629221284:AAFRFeQuMoeBHcnNU8ifQAIRLTu4CTYVU4E"
BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
INSTAGRAM_URL = "https://instagram.com/persepolisToken"  # آدرس اینستاگرام خود را اینجا قرار دهید
TWITTER_URL = "https://twitter.com/persepolisToken"      # آدرس توییتر خود را اینجا قرار دهید
ADMIN_CHAT_ID = 6661478622
REQUIRED_REFERRALS = 5

BASE_REWARD = 1000
EXTRA_REWARD = 200

BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = TeleBot(TOKEN, threaded=True)

def init_db():
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referred_by INTEGER,
            ref_count INTEGER DEFAULT 0,
            submitted INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            user_info TEXT,
            instagram_id TEXT,
            wallet TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS captcha (
            user_id INTEGER PRIMARY KEY,
            answer INTEGER,
            pending_referrer INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_data(user_id):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT ref_count, submitted, paid, verified FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_user_after_verify(user_id, referrer_id):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, referred_by, verified) VALUES (?, ?, 1)", (user_id, referrer_id))
        if referrer_id and referrer_id != user_id:
            cursor.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (referrer_id,))
            conn.commit()
            try:
                cursor.execute("SELECT ref_count FROM users WHERE user_id = ?", (referrer_id,))
                ref_row = cursor.fetchone()
                current_refs = ref_row[0] if ref_row else 1
                earned_now = calculate_tokens(current_refs)
                bot.send_message(
                    referrer_id,
                    f"🎉 *یک زیرمجموعه جدید با لینک شما وارد شد!*\n\n"
                    f"👥 تعداد کل دعوت‌های شما: `{current_refs}`\n"
                    f"🎁 مجموع توکن کسب‌شده: `{earned_now}` PRS",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            conn.commit()
    else:
        cursor.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    conn.close()

def save_submission(user_id, info_text, instagram_id, wallet):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET submitted = 1, user_info = ?, instagram_id = ?, wallet = ?
        WHERE user_id = ?
    """, (info_text, instagram_id, wallet, user_id))
    conn.commit()
    conn.close()

def toggle_paid_status(user_id):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT paid FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        new_status = 0 if row[0] == 1 else 1
        cursor.execute("UPDATE users SET paid = ? WHERE user_id = ?", (new_status, user_id))
        conn.commit()
        conn.close()
        return new_status
    conn.close()
    return None

def calculate_tokens(ref_count):
    if ref_count < REQUIRED_REFERRALS:
        return 0
    extra = ref_count - REQUIRED_REFERRALS
    return BASE_REWARD + (extra * EXTRA_REWARD)

def check_channel(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    user_data = get_user_data(user_id)
    if user_data and user_data[3] == 1:
        show_main_menu(message.chat.id, user_id)
        return

    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_ans = num1 + num2

    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO captcha (user_id, answer, pending_referrer) VALUES (?, ?, ?)", (user_id, correct_ans, referrer_id))
    conn.commit()
    conn.close()

    bot.send_message(
        message.chat.id,
        f"🛡 *تایید هویت امنیتی (ضد ربات و فیک)* \n\n"
        f"لطفاً حاصل جمع زیر را به عنوان پاسخ ارسال کنید:\n"
        f"❓ {num1} + {num2} = ؟\n\n"
        f"*(عدد پاسخ را در چت ارسال کنید)*",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📋 لیست کاربران و تایید پرداخت‌ها", callback_data="admin_users"))
    markup.row(InlineKeyboardButton("👝 لیست یکجای ولت‌ها", callback_data="admin_wallets"))
    markup.row(InlineKeyboardButton("📊 دسته‌بندی مقادیر توکن یکسان", callback_data="admin_batch"))
    markup.row(InlineKeyboardButton("📈 آمار کلی ربات", callback_data="admin_stats"))
    markup.row(InlineKeyboardButton("📊 آمار تفکیکی (قیف تبدیل)", callback_data="admin_adv_stats"))
    markup.row(InlineKeyboardButton("📁 دریافت فایل خروجی CSV", callback_data="admin_export"))
    bot.send_message(message.chat.id, "پنل مدیریت ایردراپ:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return
    if call.data == "admin_users":
        show_eligible_users_direct(call.message)
    elif call.data == "admin_wallets":
        get_all_wallets_direct(call.message)
    elif call.data == "admin_batch":
        batch_by_tokens_direct(call.message)
    elif call.data == "admin_stats":
        show_stats_direct(call.message)
    elif call.data == "admin_adv_stats":
        show_advanced_stats_direct(call.message)
    elif call.data == "admin_export":
        export_csv_direct(call.message)
    bot.answer_callback_query(call.id)

def show_eligible_users_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, paid, user_info, instagram_id, wallet FROM users WHERE submitted = 1 ORDER BY paid ASC, ref_count DESC")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "⚠️ هنوز هیچ کاربری فرم اطلاعاتش را نفرستاده است.")
        return
    for uid, ref_cnt, paid_status, info, insta, wlt in rows:
        earned_tokens = calculate_tokens(ref_cnt)
        status_text = "✅ پرداخت شده" if paid_status == 1 else "⏳ در انتظار پرداخت"
        text = f"👤 آیدی عددی: `{uid}`\n📸 اینستاگرام: `{insta}`\n👝 ولت: `{wlt}`\n👥 دعوت: `{ref_cnt}`\n🎁 توکن: `{earned_tokens}`\n📌 وضعیت: `{status_text}`"
        markup = InlineKeyboardMarkup()
        btn_text = "❌ لغو" if paid_status == 1 else "✅ تایید"
        markup.row(InlineKeyboardButton(btn_text, callback_data=f"pay_{uid}"))
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")

def get_all_wallets_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet, instagram_id FROM users WHERE submitted = 1 AND paid = 0 ORDER BY ref_count DESC")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "⚠️ کاربر در انتظار پرداختی نیست.")
        return
    text = "👝 لیست ولت‌ها:\n\n"
    for uid, ref_cnt, wlt, insta in rows:
        tokens = calculate_tokens(ref_cnt)
        text += f"📌 آیدی: `{uid}`\nولت: `{wlt}`\nمقدار: `{tokens}`\n---\n"
    bot.send_message(ADMIN_CHAT_ID, text, parse_mode="Markdown")

def batch_by_tokens_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet FROM users WHERE submitted = 1 AND paid = 0")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return
    grouped = defaultdict(list)
    for uid, ref_cnt, wlt in rows:
        tokens = calculate_tokens(ref_cnt)
        if tokens > 0 and wlt:
            grouped[tokens].append(wlt)
    text = "📊 دسته‌بندی توکن‌ها:\n\n"
    for tokens, wallets in grouped.items():
        text += f"🎁 مقدار: `{tokens}`\nلیست:\n" + "\n".join(wallets) + "\n---\n"
    bot.send_message(ADMIN_CHAT_ID, text, parse_mode="Markdown")

def show_stats_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    t_u = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE submitted = 1")
    t_s = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE paid = 1")
    t_p = cursor.fetchone()[0]
    conn.close()
    bot.send_message(ADMIN_CHAT_ID, f"📊 آمار:\nکل: {t_u}\nثبت فرم: {t_s}\nپرداختی: {t_p}", parse_mode="Markdown")

def show_advanced_stats_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    s0 = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE verified = 1")
    s1 = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE submitted = 1")
    s2 = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE paid = 1")
    s3 = cursor.fetchone()[0]
    conn.close()
    bot.send_message(ADMIN_CHAT_ID, f"قیف تبدیل:\nاستارت: {s0}\nتایید: {s1}\nفرم: {s2}\nپرداخت: {s3}", parse_mode="Markdown")

def export_csv_direct(message):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, referred_by, ref_count, submitted, paid, verified, instagram_id, wallet FROM users")
    rows = cursor.fetchall()
    conn.close()
    output = io.StringIO()
    output.write("user_id,referred_by,ref_count,submitted,paid,verified,instagram_id,wallet\n")
    for row in rows:
        output.write(",".join(str(v) if v is not None else '' for v in row) + '\n')
    output.seek(0)
    file_bytes = io.BytesIO(output.getvalue().encode('utf-8'))
    file_bytes.name = 'users.csv'
    bot.send_document(ADMIN_CHAT_ID, file_bytes)

def show_main_menu(chat_id, user_id):
    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    earned = calculate_tokens(ref_count)
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📢 کانال تلگرام", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        InlineKeyboardButton("📸 اینستاگرام", url=INSTAGRAM_URL)
    )
    markup.row(InlineKeyboardButton("🐦 توییتر (ایکس)", url=TWITTER_URL))
    markup.row(InlineKeyboardButton("🔗 دریافت لینک دعوت اختصاصی", callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton("🏆 برترین دعوت‌کنندگان", callback_data="leaderboard"))
    markup.row(InlineKeyboardButton("📊 وضعیت من", callback_data="my_status"), InlineKeyboardButton("📝 ارسال اطلاعات و ولت", callback_data="submit_info"))
    
    caption_text = (
        f"🔴 *به ربات رسمی ایردراپ توکن پرسپولیس (PRS) خوش آمدید* 🏆\n\n"
        f"🪙 *معرفی پروژه:* توکن هواداری پرسپولیس بستری مدرن برای هواداران عزیز است تا در اکوسیستم دیجیتال باشگاه سهم داشته باشند.\n\n"
        f"🎁 *سیستم پاداش‌دهی و ایردراپ:*\n"
        f"▫️ پاداش پایه برای ورود و فعال‌سازی: `{BASE_REWARD} PRS`\n"
        f"▫️ شرط دریافت پاداش: دعوت از حداقل `{REQUIRED_REFERRALS}` دوست با لینک اختصاصی\n"
        f"▫️ پاداش به ازای هر دعوت مازاد: `{EXTRA_REWARD} PRS`\n\n"
        f"📋 *راهنمای دریافت ایردراپ:*\n"
        f"۱. در کانال تلگرام، اینستاگرام و توییتر ما حتماً عضو شوید.\n"
        f"۲. لینک دعوت اختصاصی خود را بگیرید و به دوستانتان بدهید.\n"
        f"۳. پس از رسیدن به حد نصاب، اطلاعات و آدرس ولت خود را ثبت کنید.\n\n"
        f"📊 *وضعیت شما در ربات:*\n"
        f"👥 دعوت‌های شما: `{ref_count}`\n"
        f"🎁 توکن کسب‌شده: `{earned} PRS`"
    )
    
    try:
        bot.send_photo(
            chat_id=chat_id,
            photo=BANNER_FILE_ID,
            caption=caption_text,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception:
        bot.send_message(
            chat_id=chat_id,
            text=caption_text,
            parse_mode="Markdown",
            reply_markup=markup
        )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id == ADMIN_CHAT_ID:
        if text.startswith("/search "):
            query = text.replace("/search", "").strip()
            conn = sqlite3.connect('/tmp/referrals.db')
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, referred_by, ref_count, submitted, paid, verified, instagram_id, wallet FROM users WHERE user_id = ? OR instagram_id LIKE ? OR wallet LIKE ?", 
                           (int(query) if query.isdigit() else 0, f"%{query}%", f"%{query}%"))
            rows = cursor.fetchall()
            conn.close()
            res = "🔍 نتیجه جستجو:\n\n"
            for r in rows:
                res += f"آیدی: `{r[0]}` | اینستا: `{r[6]}` | ولت: `{r[7]}`\n---\n"
            bot.send_message(ADMIN_CHAT_ID, res, parse_mode="Markdown")
            return
        elif text.startswith("/deleteuser "):
            target_id = text.replace("/deleteuser", "").strip()
            if target_id.isdigit():
                conn = sqlite3.connect('/tmp/referrals.db')
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE user_id = ?", (int(target_id),))
                conn.commit()
                conn.close()
                bot.send_message(ADMIN_CHAT_ID, f"✅ کاربر {target_id} حذف شد.")
            return
        elif text.startswith("/sendall "):
            broadcast_msg = text.replace("/sendall", "").strip()
            conn = sqlite3.connect('/tmp/referrals.db')
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            conn.close()
            for u in all_users:
                try:
                    bot.send_message(u[0], f"📢 {broadcast_msg}")
                except Exception:
                    pass
            bot.send_message(ADMIN_CHAT_ID, f"✅ ارسال همگانی انجام شد.")
            return

    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT answer, pending_referrer FROM captcha WHERE user_id = ?", (user_id,))
    captcha_data = cursor.fetchone()
    if captcha_data:
        correct_ans, referrer_id = captcha_data
        if text.isdigit() and int(text) == correct_ans:
            cursor.execute("DELETE FROM captcha WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            register_user_after_verify(user_id, referrer_id)
            show_main_menu(user_id, user_id)
        else:
            conn.close()
            bot.send_message(user_id, "❌ پاسخ اشتباه است. دوباره تلاش کنید.")
        return
    conn.close()

    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ? AND submitted = 0", (user_id,))
    is_submitting = cursor.fetchone()
    conn.close()

    if is_submitting:
        parts = text.split('\n')
        if len(parts) >= 3:
            save_submission(user_id, parts[0], parts[1], parts[2])
            bot.send_message(user_id, "✅ اطلاعات با موفقیت ثبت شد.")
            show_main_menu(user_id, user_id)
        else:
            bot.send_message(user_id, "⚠️ فرمت اطلاعات ارسالی ناقص است.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    if call.data == "check_join":
        if check_channel(user_id):
            bot.answer_callback_query(call.id, "✅ تایید شد!")
            show_main_menu(call.message.chat.id, user_id)
        else:
            bot.answer_callback_query(call.id, "❌ عضو کانال نشده‌اید!", show_alert=True)
    elif call.data == "get_ref_link":
        bot.answer_callback_query(call.id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        link_text = (
            f"🔗 *لینک دعوت اختصاصی شما*\n\n"
            f"با ارسال این لینک به دوستان خود، به ازای هر دعوت مازاد پاداش بگیرید:\n\n"
            f"`{ref_link}`\n\n"
            f"*(برای کپی کردن، کافیست روی لینک بالا لمس کنید)*"
        )
        try:
            bot.send_photo(
                chat_id=user_id,
                photo=BANNER_FILE_ID,
                caption=link_text,
                parse_mode="Markdown"
            )
        except Exception:
            bot.send_message(
                chat_id=user_id,
                text=link_text,
                parse_mode="Markdown"
            )
    elif call.data == "leaderboard":
        bot.answer_callback_query(call.id)
        conn = sqlite3.connect('/tmp/referrals.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, ref_count FROM users ORDER BY ref_count DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        text = "🏆 *۱۰ کاربر برتر ایردراپ (بیشترین دعوت)*:\n\n"
        for idx, (uid, r_cnt) in enumerate(rows, 1):
            text += f"{idx}. آیدی: `{uid}` — 👥 تعداد دعوت: *{r_cnt}*\n"
        bot.send_message(user_id, text, parse_mode="Markdown")
    elif call.data == "my_status":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        earned = calculate_tokens(ref_count)
        bot.answer_callback_query(call.id, f"📊 تعداد دعوت‌ها: {ref_count} | توکن: {earned} PRS", show_alert=True)
    elif call.data == "submit_info":
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "لطفاً اطلاعات را در ۳ خط بفرستید:\nخط ۱: نام و نام خانوادگی\nخط ۲: آیدی اینستاگرام\nخط ۳: آدرس ولت (ارز دیجیتال)")
    elif call.data.startswith("pay_") and user_id == ADMIN_CHAT_ID:
        target_uid = int(call.data.split("_")[1])
        toggle_paid_status(target_uid)
        bot.answer_callback_query(call.id, "وضعیت پرداخت تغییر کرد.")

if __name__ == "__main__":
    print("Bot is starting with Long Polling...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
