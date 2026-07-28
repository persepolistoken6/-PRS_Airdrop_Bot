import io
import os
import random
import sqlite3
import time
from collections import defaultdict
from telebot import TeleBot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")
BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
TWITTER_URL = "https://x.com/PersepolisPRS"
INSTAGRAM_URL = "https://instagram.com/your_instagram_page"
ADMIN_CHAT_ID = 6661478622
REQUIRED_REFERRALS = 5

BASE_REWARD = 1000
EXTRA_REWARD = 1000
DAILY_REWARD = 100
MAX_TOTAL_TOKENS_LIMIT = 500_000_000

BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = TeleBot(TOKEN, threaded=True)

def get_db_connection():
    db_dir = '/data' if os.path.exists('/data') else os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(db_dir, 'referrals.db')
    conn = sqlite3.connect(db_path, timeout=30.0)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referred_by INTEGER,
            ref_count INTEGER DEFAULT 0,
            submitted INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            wallet TEXT,
            last_daily INTEGER DEFAULT 0,
            daily_count INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS captcha (
            user_id INTEGER PRIMARY KEY,
            num1 INTEGER,
            num2 INTEGER,
            answer INTEGER,
            pending_referrer INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_data(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ref_count, submitted, paid, verified, last_daily, daily_count, wallet FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def calculate_tokens(ref_count):
    if ref_count < REQUIRED_REFERRALS:
        return 0
    extra = ref_count - REQUIRED_REFERRALS
    return BASE_REWARD + (extra * EXTRA_REWARD)

def calculate_total_tokens(ref_count, daily_count):
    base_ref_tokens = calculate_tokens(ref_count)
    daily_tokens = daily_count * DAILY_REWARD
    return base_ref_tokens + daily_tokens

def get_global_total_distributed_tokens():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ref_count, daily_count FROM users")
    rows = cursor.fetchall()
    conn.close()
    total = 0
    for r_cnt, d_cnt in rows:
        total += calculate_total_tokens(r_cnt, d_cnt)
    return total

def is_airdrop_finished():
    return get_global_total_distributed_tokens() >= MAX_TOTAL_TOKENS_LIMIT

def check_membership(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        print(f"Error checking membership: {e}")
    return False

def get_main_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📊 وضعیت من و رتبه", "🔗 دریافت لینک دعوت")
    markup.row("🎁 پاداش روزانه", "📝 ارسال / ویرایش آدرس ولت")
    markup.row("📖 راهنمای ولت و توکن", "🏆 برترین شرکت‌کنندگان")
    markup.row("🔄 به‌روزرسانی پنل کاربری", "📢 کانال تلگرام")
    markup.row("🐦 توییتر (ایکس)", "📸 اینستاگرام")
    return markup

def get_admin_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👝 مدیریت و تایید ولت‌ها", "📊 گزارش کلی توکن‌ها")
    markup.row("🔍 جستجوی کاربر (آیدی یا ولت)", "📁 آپلود اکسل پرداختی‌ها")
    markup.row("🟢 اکسل پرداخت‌شده‌ها", "🟡 اکسل در انتظار پرداخت")
    markup.row("📊 گزارش تفکیکی کامل (فایل)", "📈 آمار کلی ربات")
    markup.row("🔄 به‌روزرسانی پنل ادمین", "🔙 خروج از حالت ادمین / منوی اصلی")
    return markup

def register_user_after_verify(user_id, referrer_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        actual_referrer = referrer_id if (referrer_id and referrer_id != user_id) else None
        cursor.execute("INSERT INTO users (user_id, referred_by, verified) VALUES (?, ?, 1)", (user_id, actual_referrer))
        
        if actual_referrer:
            cursor.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (actual_referrer,))
            conn.commit()
            try:
                cursor.execute("SELECT ref_count, daily_count FROM users WHERE user_id = ?", (actual_referrer,))
                ref_row = cursor.fetchone()
                current_refs = ref_row[0] if ref_row else 1
                d_count = ref_row[1] if ref_row else 0
                earned_now = calculate_total_tokens(current_refs, d_count)
                bot.send_message(
                    actual_referrer,
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
        current_referred_by = row[1]
        if not current_referred_by and referrer_id and referrer_id != user_id:
            cursor.execute("UPDATE users SET verified = 1, referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
            cursor.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (referrer_id,))
            conn.commit()
            try:
                cursor.execute("SELECT ref_count, daily_count FROM users WHERE user_id = ?", (referrer_id,))
                ref_row = cursor.fetchone()
                current_refs = ref_row[0] if ref_row else 1
                d_count = ref_row[1] if ref_row else 0
                earned_now = calculate_total_tokens(current_refs, d_count)
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
            cursor.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
    conn.close()

def save_submission(user_id, wallet, current_submitted_status):
    new_status = 1 if current_submitted_status == 0 else 2
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET submitted = ?, wallet = ?
        WHERE user_id = ?
    """, (new_status, wallet, user_id))
    conn.commit()
    conn.close()

def get_ref_details(ref_count):
    if ref_count >= REQUIRED_REFERRALS:
        base_used = REQUIRED_REFERRALS
        extra_count = ref_count - REQUIRED_REFERRALS
    else:
        base_used = ref_count
        extra_count = 0
    return base_used, extra_count

def send_captcha(chat_id, user_id, referrer_id):
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_ans = num1 + num2

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO captcha (user_id, num1, num2, answer, pending_referrer) VALUES (?, ?, ?, ?, ?)", (user_id, num1, num2, correct_ans, referrer_id))
    conn.commit()
    conn.close()

    bot.send_message(
        chat_id,
        f"🛡 *تایید هویت امنیتی (ضد ربات و فیک)* \n\n"
        f"لطفاً حاصل جمع زیر را به عنوان پاسخ ارسال کنید:\n"
        f"❓ {num1} + {num2} = ؟\n\n"
        f"*(عدد پاسخ را در چت ارسال کنید)*",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if user_id == ADMIN_CHAT_ID:
        bot.send_message(
            user_id, 
            "👑 *به پنل مدیریت دائمی خوش آمدید.*\nاز دکمه‌های منوی پایین استفاده کنید.", 
            reply_markup=get_admin_reply_markup(), 
            parse_mode="Markdown"
        )
        return

    if is_airdrop_finished():
        bot.send_message(user_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    if message.text and message.text.startswith('/menu'):
        if not check_membership(user_id):
            ask_to_join(message.chat.id, 0)
            return
        show_main_menu(message.chat.id, user_id)
        return

    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    # اصلاح شده: اگر کاربر روی لینک خود کلیک کرد، فقط اخطار داده شود و متوقف گردد
    if referrer_id == user_id:
        bot.send_message(
            message.chat.id, 
            "⚠️ **شما نمی‌توانید روی لینک دعوت خودتان کلیک کنید!**\n\nلطفاً این لینک را برای دوستان خود ارسال کنید تا از طریق آن وارد ربات شوند.",
            parse_mode="Markdown"
        )
        return

    user_data = get_user_data(user_id)
    if user_data and user_data[3] >= 2:
        if not check_membership(user_id):
            ask_to_join(message.chat.id, referrer_id if referrer_id else 0)
            return
        show_main_menu(message.chat.id, user_id)
        return

    send_captcha(message.chat.id, user_id, referrer_id)

def ask_to_join(chat_id, referrer_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📢 عضویت در کانال رسمی", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    markup.row(InlineKeyboardButton("✅ عضو شدم، تایید کن", callback_data=f"check_join_{referrer_id}"))
    
    bot.send_message(
        chat_id,
        f"⚠️ **لطفاً برای ادامه کار ابتدا در کانال ما عضو شوید:**\n\n"
        f"▫️ {CHANNEL_ID}\n\n"
        f"پس از عضویت، روی دکمه‌ی «عضو شدم، تایید کن» بزنید.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

def get_user_rank(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, daily_count FROM users")
    rows = cursor.fetchall()
    conn.close()
    
    scored_users = []
    for uid, r_cnt, d_cnt in rows:
        total = calculate_total_tokens(r_cnt, d_cnt)
        scored_users.append((uid, total))
    
    scored_users.sort(key=lambda x: x[1], reverse=True)
    for idx, (uid, _) in enumerate(scored_users, 1):
        if uid == user_id:
            return idx
    return "محاسبه‌نشده"

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    bot.send_message(
        ADMIN_CHAT_ID,
        "👑 *پنل مدیریت ثابت فعال است.*",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def show_token_summary_direct(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ref_count, daily_count, paid FROM users WHERE submitted > 0")
    rows = cursor.fetchall()
    conn.close()

    total_all_tokens = get_global_total_distributed_tokens()
    paid_tokens = 0
    unpaid_tokens = 0

    for r_cnt, d_cnt, paid in rows:
        t_tokens = calculate_total_tokens(r_cnt, d_cnt)
        if paid == 1:
            paid_tokens += t_tokens
        else:
            unpaid_tokens += t_tokens

    text = (
        f"📊 *گزارش جامع توکن‌های ایردراپ:*\n\n"
        f"🪙 کل توکن‌های کسب‌شده توسط تمام کاربران: `{total_all_tokens:,} PRS`\n"
        f"🟢 کل توکن‌های پرداخت‌شده به کاربران تایید شده: `{paid_tokens:,} PRS`\n"
        f"🟡 کل توکن‌های در انتظار پرداخت (پرداخت‌نشده): `{unpaid_tokens:,} PRS`\n\n"
        f"📌 سقف کل ایردراپ: `{MAX_TOTAL_TOKENS_LIMIT:,} PRS`"
    )
    bot.send_message(chat_id, text, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def send_paginated_wallets(message, offset=0, edit=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet, paid, daily_count FROM users WHERE submitted > 0 ORDER BY ref_count DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        msg = "⚠️ هیچ کاربری هنوز فرم اطلاعاتش را ارسال نکرده است."
        if edit:
            bot.edit_message_text(msg, chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
        else:
            bot.send_message(ADMIN_CHAT_ID, msg, reply_markup=get_admin_reply_markup())
        return

    limit = 5
    page_rows = rows[offset:offset+limit]

    text = f"👝 **لیست کاربران ثبت‌نام کرده (مجموع: {len(rows)} نفر):**\n\n"
    markup = InlineKeyboardMarkup()

    for uid, ref_cnt, wlt, paid, d_count in page_rows:
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        base_used, extra_count = get_ref_details(ref_cnt)
        status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
        
        text += f"📌 آیدی عددی: `{uid}`\n" \
                f"👝 ولت: `{wlt}`\n" \
                f"👥 دعوت ثابت: {base_used} | مازاد: {extra_count} (کل: {ref_cnt})\n" \
                f"🎁 توکن کل: `{total_tokens:,} PRS` (پاداش روزانه: {d_count} بار)\n" \
                f"وضعیت: *{status_str}*\n" \
                f"----------------------------------\n"
        
        btn_pay = InlineKeyboardButton(f"✅ تایید ({uid})", callback_data=f"admin_pay_{uid}_yes")
        btn_unpay = InlineKeyboardButton(f"❌ لغو ({uid})", callback_data=f"admin_pay_{uid}_no")
        markup.row(btn_pay, btn_unpay)

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"admin_page_{offset - limit}"))
    if offset + limit < len(rows):
        nav_buttons.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"admin_page_{offset + limit}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    if edit:
        try:
            bot.edit_message_text(text, chat_id=ADMIN_CHAT_ID, message_id=message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass
    else:
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")

def send_status_excel_report(chat_id, status_filter):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet, paid, daily_count FROM users WHERE submitted > 0 AND paid = ? ORDER BY ref_count DESC", (status_filter,))
    rows = cursor.fetchall()
    conn.close()

    status_name = "پرداخت‌شده" if status_filter == 1 else "در انتظار پرداخت"
    if not rows:
        bot.send_message(chat_id, f"⚠️ هیچ کاربری در وضعیت «{status_name}» وجود ندارد.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Wallet,Referrals,Daily Bonus Count,Total Tokens,Status\n"
    for uid, ref_cnt, wlt, paid, d_count in rows:
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        st_text = "Paid" if paid == 1 else "Pending"
        csv_content += f"{uid},{wlt},{ref_cnt},{d_count},{total_tokens},{st_text}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
    file_name = 'paid_users.csv' if status_filter == 1 else 'pending_users.csv'
    file_bytes.name = file_name
    
    caption_text = f"📁 فایل گزارش کاربران **{status_name}** (فرمت سازگار با اکسل/CSV)"
    bot.send_document(chat_id, file_bytes, caption=caption_text, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def send_detailed_report_file(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, referred_by, ref_count, submitted, paid, verified, wallet, last_daily, daily_count FROM users ORDER BY paid ASC, ref_count DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(chat_id, "⚠️ هیچ کاربری در دیتابیس ثبت نشده است.", reply_markup=get_admin_reply_markup())
        return

    csv_content = "User ID,Referred By,Referral Count,Submitted Status,Paid Status,Verified Status,Wallet,Last Daily Timestamp,Daily Bonus Count,Total Tokens\n"
    for uid, ref_by, ref_cnt, submitted, paid, verified, wlt, last_daily, d_count in rows:
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        wallet_clean = str(wlt).replace(',', '_') if wlt else "None"
        csv_content += f"{uid},{ref_by},{ref_cnt},{submitted},{paid},{verified},{wallet_clean},{last_daily},{d_count},{total_tokens}\n"

    file_bytes = io.BytesIO(csv_content.encode('utf-8'))
    file_bytes.name = 'all_users_complete_database_report.csv'
    
    bot.send_document(
        chat_id, 
        file_bytes, 
        caption="📁 **گزارش اکسل جامع و کامل تمام اطلاعات کاربران** (شامل آیدی، ولت، تعداد رفال، وضعیت پرداخت، پاداش روزانه و تمامی جزئیات بدون کم‌وکاست).", 
        reply_markup=get_admin_reply_markup(), 
        parse_mode="Markdown"
    )

def show_stats_direct(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    t_u = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE submitted > 0")
    t_s = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE paid = 1")
    t_p = cursor.fetchone()[0]
    conn.close()
    total_tokens_all = get_global_total_distributed_tokens()
    bot.send_message(chat_id, f"📊 آمار کلی ربات:\n\n👤 کل کاربران استارت کرده: {t_u}\n📝 تعداد ثبت‌فرم‌ها: {t_s}\n💰 پرداخت‌شده‌ها: {t_p}\n🪙 کل توکن توزیع‌شده: {total_tokens_all:,} PRS", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

def show_main_menu(chat_id, user_id, message_id=None, edit=False):
    if is_airdrop_finished():
        bot.send_message(chat_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    d_count = user_data[5] if user_data and len(user_data) > 5 else 0
    total_earned = calculate_total_tokens(ref_count, d_count)
    user_rank = get_user_rank(user_id)
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📢 کانال تلگرام", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        InlineKeyboardButton("🐦 توییتر (ایکس)", url=TWITTER_URL)
    )
    markup.row(InlineKeyboardButton("📸 اینستاگرام پرسپولیس", url=INSTAGRAM_URL))
    
    markup.row(InlineKeyboardButton("🔗 دریافت لینک دعوت جذاب و اختصاصی", callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton("🎁 پاداش روزانه (100 PRS)", callback_data="daily_bonus"))
    markup.row(InlineKeyboardButton("📖 راهنمای ولت و توکن PRS", callback_data="wallet_guide"))
    markup.row(InlineKeyboardButton("🏆 برترین شرکت‌کنندگان (تاپ ۱۰)", callback_data="leaderboard"))
    markup.row(InlineKeyboardButton("📊 وضعیت من و رتبه", callback_data="my_status"), InlineKeyboardButton("📝 ارسال / ویرایش ولت", callback_data="submit_info"))
    markup.row(InlineKeyboardButton("🔄 به‌روزرسانی پنل کاربری", callback_data="refresh_menu"))

    caption_text = (
        f"🔴 *به ربات رسمی ایردراپ توکن هواداری پرسپولیس (PRS) خوش آمدید* 🏆\n\n"
        f"🪙 *معرفی پروژه:* توکن هواداری پرسپولیس بستری مدرن برای هواداران عزیز است تا در اکوسیستم دیجیتال باشگاه سهم داشته باشند.\n\n"
        f"🎁 *سیستم پاداش‌دهی و ایردراپ:*\n"
        f"▫️ پاداش پایه: `{BASE_REWARD} PRS` (پس از عضویت در کانال و دعوت `{REQUIRED_REFERRALS}` دوست)\n"
        f"▫️ پاداش روزانه: `{DAILY_REWARD} PRS` (فعال‌سازی پس از تکمیل ۵ دعوت و هر ۲۴ ساعت یک‌بار)\n"
        f"▫️ پاداش به ازای هر دعوت مازاد: `{EXTRA_REWARD} PRS`\n\n"
        f"📊 *وضعیت حساب شما:*\n"
        f"👥 دعوت‌های شما: `{ref_count} / {REQUIRED_REFERRALS}`\n"
        f"🏅 رتبه شما در بین کاربران: `{user_rank}`\n"
        f"🎁 مجموع توکن کسب‌شده: `{total_earned:,} PRS`"
    )
    
    reply_markup_kb = get_main_reply_markup()

    if edit and message_id:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            bot.send_message(chat_id, "👇 منوی دسترسی سریع همیشه در پایین صفحه شما قرار دارد:", reply_markup=reply_markup_kb)
            return
        except Exception:
            pass

    try:
        if BANNER_FILE_ID:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
        else:
            raise Exception("No banner")
    except Exception:
        try:
            bot.send_message(chat_id=chat_id, text=caption_text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"Error sending main menu text: {e}")

    try:
        bot.send_message(chat_id=chat_id, text="👇 منوی دسترسی سریع همیشه در پایین صفحه شما قرار دارد:", reply_markup=reply_markup_kb)
    except Exception as e:
        print(f"Error sending reply markup: {e}")

@bot.message_handler(content_types=['document'])
def handle_admin_documents(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE submitted > 0")
    valid_users = {row[0] for row in cursor.fetchall()}
    conn.close()

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_text = downloaded_file.decode('utf-8', errors='ignore')
        
        lines = file_text.splitlines()
        updated_count = 0
        not_found_count = 0
        
        conn = get_db_connection()
        cursor = conn.cursor()

        for line in lines:
            line = line.strip()
            if not line or line.startswith("User") or line.startswith("user"):
                continue
            
            parts = [p.strip() for p in line.replace(';', ',').split(',')]
            target_id = None
            
            for part in parts:
                if part.isdigit():
                    val = int(part)
                    if val in valid_users or val > 10000:
                        target_id = val
                        break
            
            if target_id:
                cursor.execute("UPDATE users SET paid = 1 WHERE user_id = ?", (target_id,))
                if cursor.rowcount > 0:
                    updated_count += 1
                else:
                    not_found_count += 1
            else:
                not_found_count += 1

        conn.commit()
        conn.close()

        bot.send_message(
            ADMIN_CHAT_ID,
            f"✅ **فایل پرداختی با موفقیت پردازش شد!**\n\n"
            f"🟢 تعداد کاربرانی که وضعیت‌شان به «پرداخت‌شده» تغییر یافت: `{updated_count}` نفر\n"
            f"⚠️ شناسایی‌نشده یا نامعتبر: `{not_found_count}` مورد",
            reply_markup=get_admin_reply_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ خطا در پردازش فایل اکسل/متنی:\n`{e}`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    text = text.translate(persian_to_english)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT num1, num2, answer, pending_referrer FROM captcha WHERE user_id = ?", (user_id,))
    captcha_data = cursor.fetchone()
    conn.close()

    if captcha_data:
        n1, n2, correct_ans, referrer_id = captcha_data
        if text.isdigit() and int(text) == correct_ans:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM captcha WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            
            if not check_membership(user_id):
                ask_to_join(chat_id, referrer_id if referrer_id else 0)
                return

            register_user_after_verify(user_id, referrer_id)
            show_main_menu(chat_id, user_id)
        else:
            new_n1 = random.randint(1, 10)
            new_n2 = random.randint(1, 10)
            new_correct_ans = new_n1 + new_n2

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE captcha SET num1 = ?, num2 = ?, answer = ? WHERE user_id = ?", (new_n1, new_n2, new_correct_ans, user_id))
            conn.commit()
            conn.close()

            bot.send_message(
                chat_id, 
                f"❌ پاسخ اشتباه است!\n\n"
                f"🛡 یک سوال امنیتی جدید برای شما ارسال شد:\n"
                f"❓ لطفاً حاصل جمع {new_n1} + {new_n2} را بفرستید:"
            )
        return

    if user_id == ADMIN_CHAT_ID:
        if text == "👝 مدیریت و تایید ولت‌ها":
            send_paginated_wallets(message, offset=0)
            return
        elif text == "📊 گزارش کلی توکن‌ها":
            show_token_summary_direct(ADMIN_CHAT_ID)
            return
        elif text == "🔍 جستجوی کاربر (آیدی یا ولت)":
            bot.send_message(ADMIN_CHAT_ID, "🔍 برای جستجو، دستور زیر را ارسال کنید:\n`/search [آیدی عددی یا بخشی از ولت]`", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text == "📁 آپلود اکسل پرداختی‌ها":
            bot.send_message(ADMIN_CHAT_ID, "📁 لطفاً فایل خروجی پرداختی خود (فرمت CSV یا متنی حاوی آیدی یا ولت کاربران) را مستقیماً در همین چت آپلود کنید تا وضعیت آن‌ها اتوماتیک به «پرداخت‌شده» تغییر یابد.", reply_markup=get_admin_reply_markup())
            return
        elif text == "🟢 اکسل پرداخت‌شده‌ها":
            send_status_excel_report(ADMIN_CHAT_ID, status_filter=1)
            return
        elif text == "🟡 اکسل در انتظار پرداخت":
            send_status_excel_report(ADMIN_CHAT_ID, status_filter=0)
            return
        elif text == "📊 گزارش تفکیکی کامل (فایل)":
            send_detailed_report_file(ADMIN_CHAT_ID)
            return
        elif text == "📈 آمار کلی ربات":
            show_stats_direct(ADMIN_CHAT_ID)
            return
        elif text == "🔄 به‌روزرسانی پنل ادمین":
            bot.send_message(ADMIN_CHAT_ID, "🔄 پنل مدیریت با موفقیت به‌روزرسانی و بازنشانی شد.", reply_markup=get_admin_reply_markup())
            return
        elif text == "🔙 خروج از حالت ادمین / منوی اصلی":
            bot.send_message(ADMIN_CHAT_ID, "مجدداً پنل مدیریتی ثابت فعال است.", reply_markup=get_admin_reply_markup())
            return
        elif text.startswith("/search "):
            query = text.replace("/search", "").strip()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, referred_by, ref_count, submitted, paid, verified, wallet, daily_count FROM users WHERE user_id = ? OR wallet LIKE ?", 
                           (int(query) if query.isdigit() else 0, f"%{query}%"))
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                bot.send_message(ADMIN_CHAT_ID, "❌ هیچ کاربری با این مشخصات پیدا نشد.", reply_markup=get_admin_reply_markup())
                return
            res = "🔍 *نتیجه جستجوی ادمین (بر اساس آیدی عددی یا ولت):*\n\n"
            for r in rows:
                ref_cnt = r[2]
                d_cnt = r[7] if len(r) > 7 else 0
                total_tokens = calculate_total_tokens(ref_cnt, d_cnt)
                base_used, extra_count = get_ref_details(ref_cnt)
                res += f"👤 آیدی عددی: `{r[0]}`\n👥 کل رفال: {ref_cnt} (ثابت: {base_used} | مازاد: {extra_count})\n🎁 توکن کل: {total_tokens:,} PRS\n👝 ولت: `{r[6]}`\n📌 ثبت فرم: `{r[3]}` | پرداخت: `{r[4]}`\n---\n"
            bot.send_message(ADMIN_CHAT_ID, res, reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            return
        elif text.startswith("/deleteuser "):
            target_id = text.replace("/deleteuser", "").strip()
            if target_id.isdigit():
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE user_id = ?", (int(target_id),))
                cursor.execute("DELETE FROM captcha WHERE user_id = ?", (int(target_id),))
                conn.commit()
                conn.close()
                bot.send_message(ADMIN_CHAT_ID, f"✅ کاربر با آیدی عددی `{target_id}` به طور کامل از دیتابیس حذف شد.", reply_markup=get_admin_reply_markup(), parse_mode="Markdown")
            else:
                bot.send_message(ADMIN_CHAT_ID, "⚠️ آیدی عددی وارد شده معتبر نیست.", reply_markup=get_admin_reply_markup())
            return
        elif text.startswith("/sendall "):
            broadcast_msg = text.replace("/sendall", "").strip()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            conn.close()
            success_count = 0
            for u in all_users:
                try:
                    bot.send_message(u[0], f"📢 {broadcast_msg}")
                    success_count += 1
                except Exception:
                    pass
            bot.send_message(ADMIN_CHAT_ID, f"✅ ارسال همگانی با موفقیت به {success_count} کاربر انجام شد.", reply_markup=get_admin_reply_markup())
            return

    if is_airdrop_finished() and user_id != ADMIN_CHAT_ID:
        bot.send_message(user_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    if not check_membership(user_id):
        ask_to_join(chat_id, 0)
        return

    if text == "📊 وضعیت من و رتبه":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        wallet = user_data[6] if user_data and len(user_data) > 6 else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 مجموع توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"👝 آدرس ولت فعلی: `{wallet}`"
        )
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
        return
    elif text == "🔗 دریافت لینک دعوت":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        link_text = (
            f"🔥 بزرگترین ایردراپ توکن هواداری پرسپولیس (PRS) 🔥\n\n"
            f"🏆 فرصت استثنایی برای دریافت توکن رایگان و ورود به اکوسیستم دیجیتال پرسپولیس!\n"
            f"🎁 همین الان با لینک زیر وارد ربات شو و پاداش ورودت رو بگیر:\n\n"
            f"{ref_link}\n\n"
            f"این پیام رو برای دوستان خود ارسال کنید"
        )
        try:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=link_text)
        except Exception:
            bot.send_message(chat_id=chat_id, text=link_text)
        return
    elif text == "🎁 پاداش روزانه":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        if ref_count < REQUIRED_REFERRALS:
            bot.send_message(chat_id, f"⚠️ پاداش روزانه قفل است!\nبرای باز شدن آن باید حداقل {REQUIRED_REFERRALS} دوست دعوت کنید.")
            return
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        if current_time - last_daily < 86400:
            remaining = 86400 - (current_time - last_daily)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.send_message(chat_id, f"⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!\nلطفاً پس از {hours} ساعت و {minutes} دقیقه دیگر تلاش کنید.")
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_daily = ?, daily_count = daily_count + 1 WHERE user_id = ?", (current_time, user_id))
            conn.commit()
            conn.close()
            bot.send_message(chat_id, f"🎁 تبریک! مبلغ {DAILY_REWARD} توکن PRS به عنوان پاداش روزانه به حساب شما اضافه شد.")
        return
    elif text == "📖 راهنمای ولت و توکن":
        guide_text = (
            f"📖 *راهنمای گام‌به‌گام نصب کیف پول و دریافت آدرس (Wallet):*\n\n"
            f"🔹 **مقدمه:** برای دریافت توکن‌های PRS، به یک کیف پول معتبر ارز دیجیتال نیاز دارید که از شبکه پروژه پشتیبانی کند (مانند Trust Wallet یا MetaMask).\n\n"
            f"📱 **مرحله اول: نصب کیف پول**\n"
            f"• اپلیکیشن **Trust Wallet** را از گوگل‌پلی (اندروید) یا اپ‌استور (آیفون) دانلود و نصب کنید.\n• یک کیف پول جدید بسازید و کلمات بازیابی (Seed Phrase) را یادداشت و در جای امن نگه دارید.\n\n"
            f"🪙 **مرحله دوم: افزودن سفارشی توکن (Custom Token)**\n"
            f"• در صفحه اصلی تراست ولت، روی آیکون تنظیمات یا علامت `+` در بالا سمت راست بزنید.\n• شبکه (Network) را روی شبکه اصلی توکن قرار دهید.\n• آدرس قرارداد (Contract Address) توکن پرسپولیس را وارد کنید تا توکن به لیست شما اضافه شود.\n\n"
            f"📋 **مرحله سوم: کپی کردن آدرس ولت**\n"
            f"• در لیست ارزهای تراست ولت، روی توکن **PRS** (یا ارز بستر پروژه) بزنید.\n• گزینه **Receive** یا **Copy** را انتخاب کنید تا آدرس ولت شما کپی شود.\n• در نهایت از طریق دکمه «📝 ارسال / ویرایش آدرس ولت» در این ربات، آدرس کپی‌شده را ارسال کنید."
        )
        bot.send_message(chat_id, guide_text, parse_mode="Markdown")
        return
    elif text == "🏆 برترین شرکت‌کنندگان":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, ref_count, daily_count FROM users")
        rows = cursor.fetchall()
        conn.close()
        
        ranked_list = []
        for uid, r_cnt, d_cnt in rows:
            total_t = calculate_total_tokens(r_cnt, d_cnt)
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: x[2], reverse=True)
        top_10 = ranked_list[:10]
        
        text = "🏆 *۱۰ شرکت‌کننده برتر ایردراپ (براساس مجموع توکن‌ها)*:\n\n"
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text += f"{idx}. آیدی: `{uid}` — 🎁 توکن کل: *{total_t:,} PRS* (دعوت: {r_cnt})\n"
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_main_reply_markup())
        return
    elif text == "🔄 به‌روزرسانی پنل کاربری":
        show_main_menu(chat_id, user_id)
        return
    elif text == "📝 ارسال / ویرایش آدرس ولت":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        submitted = user_data[1] if user_data else 0
        
        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")
        if submitted >= 2:
            errors.append("⚠️ شما سهمیه ثبت‌نام و تنها ویرایش مجاز خود را استفاده کرده‌اید و دیگر امکان تغییر ولت وجود ندارد.")
            
        if errors:
            bot.send_message(chat_id, "⚠️ **امکان ثبت/ویرایش ولت وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.", parse_mode="Markdown")
            return
        
        if submitted == 1:
            bot.send_message(chat_id, "✏️ **حالت ویرایش ولت:**\nشما قبلاً ولت خود را ثبت کرده بودید. اکنون می‌توانید آدرس ولت جدید خود را ارسال کنید (این **آخرین فرصت** شما برای ویرایش است):\n\nلطفاً آدرس ولت خود را ارسال کنید:")
        else:
            bot.send_message(chat_id, "لطفاً آدرس ولت (ارز دیجیتال) خود را ارسال کنید:")
        return
    elif text == "📢 کانال تلگرام":
        bot.send_message(chat_id, f"📢 کانال رسمی: {CHANNEL_ID}")
        return
    elif text == "🐦 توییتر (ایکس)":
        bot.send_message(chat_id, f"🐦 صفحه توییتر: {TWITTER_URL}")
        return
    elif text == "📸 اینستاگرام":
        bot.send_message(chat_id, f"📸 صفحه اینستاگرام: {INSTAGRAM_URL}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, submitted FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    is_submitting_or_editing = row and row[1] < 2

    if is_submitting_or_editing or len(text) > 10:
        if row and row[1] >= 2:
            bot.send_message(chat_id, "⚠️ شما سهمیه ویرایش خود را به اتمام رسانده‌اید و ولت شما قابل تغییر نیست.")
            return
            
        current_sub_status = row[1] if row else 0
        save_submission(user_id, text, current_sub_status)
        
        if current_sub_status == 0:
            bot.send_message(chat_id, "✅ آدرس ولت شما با موفقیت ثبت شد.\n*(توجه: شما فقط یک‌بار دیگر امکان ویرایش این ولت را دارید)*")
        else:
            bot.send_message(chat_id, "✅ آدرس ولت شما با موفقیت **ویرایش و به‌روزرسانی شد**.\n*(پرونده اطلاعات شما قفل شد و دیگر قابل تغییر نیست)*")
        
        show_main_menu(chat_id, user_id)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if is_airdrop_finished() and user_id != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "🛑 ایردراپ به اتمام رسید.", show_alert=True)
        return

    if call.data.startswith("check_join_"):
        referrer_id = int(call.data.split("_")[2])
        
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)
            return

        bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد!")
        register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        
        show_main_menu(chat_id, user_id)
        return

    if call.data == "refresh_menu":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
            ask_to_join(chat_id, 0)
            return
        bot.answer_callback_query(call.id, "🔄 پنل به‌روز شد.")
        show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
        return

    if call.data == "get_ref_link":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        
        link_text = (
            f"🔥 بزرگترین ایردراپ توکن هواداری پرسپولیس (PRS) 🔥\n\n"
            f"🏆 فرصت استثنایی برای دریافت توکن رایگان و ورود به اکوسیستم دیجیتال پرسپولیس!\n"
            f"🎁 همین الان با لینک زیر وارد ربات شو و پاداش ورودت رو بگیر:\n\n"
            f"{ref_link}\n\n"
            f"این پیام رو برای دوستان خود ارسال کنید"
        )
        try:
            bot.send_photo(chat_id=chat_id, photo=BANNER_FILE_ID, caption=link_text)
        except Exception:
            bot.send_message(chat_id=chat_id, text=link_text)
    elif call.data == "daily_bonus":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        
        if ref_count < REQUIRED_REFERRALS:
            bot.answer_callback_query(call.id, f"⚠️ پاداش روزانه قفل است!\nبرای باز شدن آن باید حداقل {REQUIRED_REFERRALS} دوست دعوت کنید.", show_alert=True)
            return
            
        current_time = int(time.time())
        last_daily = user_data[4] if user_data else 0
        
        if current_time - last_daily < 86400:
            remaining = 86400 - (current_time - last_daily)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.answer_callback_query(call.id, f"⏳ شما قبلاً پاداش امروز خود را دریافت کرده‌اید!\nلطفاً پس از {hours} ساعت و {minutes} دقیقه دیگر تلاش کنید.", show_alert=True)
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_daily = ?, daily_count = daily_count + 1 WHERE user_id = ?", (current_time, user_id))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, f"🎁 تبریک! مبلغ {DAILY_REWARD} توکن PRS به عنوان پاداش روزانه به حساب شما اضافه شد.", show_alert=True)
            show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
    elif call.data == "wallet_guide":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        guide_text = (
            f"📖 *راهنمای گام‌به‌گام نصب کیف پول و دریافت آدرس (Wallet):*\n\n"
            f"🔹 **مقدمه:** برای دریافت توکن‌های PRS، به یک کیف پول معتبر ارز دیجیتال نیاز دارید که از شبکه پروژه پشتیبانی کند (مانند Trust Wallet یا MetaMask).\n\n"
            f"📱 **مرحله اول: نصب کیف پول**\n"
            f"• اپلیکیشن **Trust Wallet** را از گوگل‌پلی (اندروید) یا اپ‌استور (آیفون) دانلود و نصب کنید.\n• یک کیف پول جدید بسازید و کلمات بازیابی (Seed Phrase) را یادداشت و در جای امن نگه دارید.\n\n"
            f"🪙 **مرحله دوم: افزودن سفارشی توکن (Custom Token)**\n"
            f"• در صفحه اصلی تراست ولت، روی آیکون تنظیمات یا علامت `+` در بالا سمت راست بزنید.\n• شبکه (Network) را روی شبکه اصلی توکن قرار دهید.\n• آدرس قرارداد (Contract Address) توکن پرسپولیس را وارد کنید تا توکن به لیست شما اضافه شود.\n\n"
            f"📋 **مرحله سوم: کپی کردن آدرس ولت**\n"
            f"• در لیست ارزهای تراست ولت، روی توکن **PRS** (یا ارز بستر پروژه) بزنید.\n• گزینه **Receive** یا **Copy** را انتخاب کنید تا آدرس ولت شما کپی شود.\n• در نهایت از طریق دکمه «📝 ارسال / ویرایش آدرس ولت» در این ربات، آدرس کپی‌شده را ارسال کنید."
        )
        bot.send_message(chat_id, guide_text, parse_mode="Markdown")
    elif call.data == "leaderboard":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, ref_count, daily_count FROM users")
        rows = cursor.fetchall()
        conn.close()
        
        ranked_list = []
        for uid, r_cnt, d_cnt in rows:
            total_t = calculate_total_tokens(r_cnt, d_cnt)
            ranked_list.append((uid, r_cnt, total_t))
        
        ranked_list.sort(key=lambda x: x[2], reverse=True)
        top_10 = ranked_list[:10]
        
        text = "🏆 *۱۰ شرکت‌کننده برتر ایردراپ (براساس مجموع توکن‌ها)*:\n\n"
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text += f"{idx}. آیدی: `{uid}` — 🎁 توکن کل: *{total_t:,} PRS* (دعوت: {r_cnt})\n"
        bot.send_message(chat_id, text, parse_mode="Markdown")
    elif call.data == "my_status":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        wallet = user_data[6] if user_data and len(user_data) > 6 else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 مجموع توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"👝 آدرس ولت فعلی: `{wallet}`"
        )
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
    elif call.data == "submit_info":
        if not check_membership(user_id):
            bot.answer_callback_query(call.id, "❌ ابتدا در کانال عضو شوید!", show_alert=True)
            return
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        submitted = user_data[1] if user_data else 0

        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")
        if submitted >= 2:
            errors.append("⚠️ شما سهمیه ثبت‌نام و تنها ویرایش مجاز خود را استفاده کرده‌اید و امکان تغییر مجدد وجود ندارد.")

        if errors:
            bot.answer_callback_query(call.id, "⚠️ شرایط لازم را ندارید!", show_alert=True)
            bot.send_message(
                chat_id,
                "⚠️ **امکان ثبت/ویرایش ولت وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.",
                parse_mode="Markdown"
            )
            return

        bot.answer_callback_query(call.id)
        if submitted == 1:
            bot.send_message(chat_id, "✏️ **حالت ویرایش ولت:**\nشما قبلاً ولت خود را ثبت کرده بودید. اکنون می‌توانید آدرس ولت جدید خود را ارسال کنید (این **آخرین فرصت** شما برای ویرایش است):\n\nلطفاً آدرس ولت خود را ارسال کنید:")
        else:
            bot.send_message(chat_id, "لطفاً آدرس ولت (ارز دیجیتال) خود را ارسال کنید:")

if __name__ == "__main__":
    print("Bot is starting...")

    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)

    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)
