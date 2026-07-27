import io
import os
import random
import sqlite3
import time
from collections import defaultdict
from telebot import TeleBot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

TOKEN = "YOUR_NEW_BOT_TOKEN"
BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
INSTAGRAM_URL = "Https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"
TWITTER_URL = "https://x.com/PersepolisPRS"
ADMIN_CHAT_ID = 6661478622
REQUIRED_REFERRALS = 5

BASE_REWARD = 1000
EXTRA_REWARD = 1000
DAILY_REWARD = 100
MAX_TOTAL_TOKENS_LIMIT = 500_000_000

BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wk1ONFWAEHF2z-vGAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = TeleBot(TOKEN, threaded=True)

def get_db_connection():
    conn = sqlite3.connect('/tmp/referrals.db', timeout=30.0)
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
            instagram_id TEXT,
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
    cursor.execute("SELECT ref_count, submitted, paid, verified, last_daily, daily_count, wallet, instagram_id FROM users WHERE user_id = ?", (user_id,))
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

def get_main_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, persistent=True)
    markup.row("📊 وضعیت من و رتبه", "🔗 دریافت لینک دعوت")
    markup.row("🎁 پاداش روزانه", "📝 ارسال/ویرایش اطلاعات و ولت")
    markup.row("📢 کانال تلگرام", "📸 اینستاگرام", "🐦 توییتر (ایکس)")
    return markup

def get_admin_reply_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, persistent=True)
    markup.row("👝 مدیریت و تایید ولت‌ها", "📊 گزارش کلی توکن‌ها")
    markup.row("📊 گزارش تفکیکی (فایل)", "📈 آمار کلی ربات")
    markup.row("🔙 خروج از حالت ادمین / منوی اصلی")
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

def save_submission(user_id, instagram_id, wallet):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET submitted = 1, instagram_id = ?, wallet = ?
        WHERE user_id = ?
    """, (instagram_id, wallet, user_id))
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
            "👑 *به پنل مدیریت دائمی خوش آمدید.*\nاز دکمه‌های ثابت زیر برای مدیریت ربات استفاده کنید:", 
            reply_markup=get_admin_reply_markup(), 
            parse_mode="Markdown"
        )
        return

    if is_airdrop_finished():
        bot.send_message(user_id, "🛑 کل توکن های ایردارپ ( ۵۰۰ میلیون PRS) توسط شرکت کننده های این ایردراپ استخراج شد و این ربات غیر فعال شد به زودی تمام توکن ها بین کاربران توزیع خواهد شد.")
        return

    if message.text and message.text.startswith('/menu'):
        show_main_menu(message.chat.id, user_id)
        return

    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    if referrer_id == user_id:
        referrer_id = None

    user_data = get_user_data(user_id)
    if user_data and user_data[3] == 1:
        show_main_menu(message.chat.id, user_id)
        return

    send_captcha(message.chat.id, user_id, referrer_id)

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
        "👑 *پنل مدیریت ثابت فعال است.*\nاز دکمه‌های پایین صفحه استفاده کنید.",
        reply_markup=get_admin_reply_markup(),
        parse_mode="Markdown"
    )

def show_token_summary_direct(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ref_count, daily_count, paid FROM users WHERE submitted = 1")
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
    cursor.execute("SELECT user_id, ref_count, wallet, instagram_id, paid, daily_count FROM users WHERE submitted = 1 ORDER BY ref_count DESC")
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

    for uid, ref_cnt, wlt, insta, paid, d_count in page_rows:
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        base_used, extra_count = get_ref_details(ref_cnt)
        status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
        
        text += f"📌 آیدی: `{uid}`\n" \
                f"👤 اینستا: `{insta}`\n" \
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

def send_detailed_report_file(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet, instagram_id, paid, daily_count FROM users WHERE submitted = 1 ORDER BY paid ASC, ref_count DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(chat_id, "⚠️ هیچ کاربری فرم اطلاعات ثبت نکرده است.", reply_markup=get_admin_reply_markup())
        return

    paid_text = "🟢 **لیست کاربران پرداخت شده:**\n\n"
    unpaid_text = "🟡 **لیست کاربران پرداخت نشده (در انتظار):**\n\n"

    paid_count = 0
    unpaid_count = 0

    for uid, ref_cnt, wlt, insta, paid, d_count in rows:
        total_tokens = calculate_total_tokens(ref_cnt, d_count)
        base_used, extra_count = get_ref_details(ref_cnt)
        user_block = (
            f"📌 آیدی عددی: `{uid}`\n"
            f"👤 اینستاگرام: `{insta}`\n"
            f"👝 آدرس ولت: `{wlt}`\n"
            f"👥 رفال ثابت: {base_used} | مازاد: {extra_count} (کل: {ref_cnt})\n"
            f"🎁 توکن کل: {total_tokens:,} PRS (پاداش روزانه: {d_count} بار)\n"
            f"----------------------------------\n"
        )
        if paid == 1:
            paid_text += user_block
            paid_count += 1
        else:
            unpaid_text += user_block
            unpaid_count += 1

    report_content = f"📊 گزارش جامع تفکیکی وضعیت پرداخت‌ها\n\n" \
                     f"🟢 تعداد پرداخت شده‌ها: {paid_count}\n" \
                     f"🟡 تعداد در انتظار پرداخت: {unpaid_count}\n\n" \
                     f"==================================\n\n" + \
                     paid_text + "\n\n==================================\n\n" + unpaid_text

    file_bytes = io.BytesIO(report_content.encode('utf-8'))
    file_bytes.name = 'detailed_airdrop_report.txt'
    bot.send_document(chat_id, file_bytes, caption="📁 گزارش متنی کامل و دسته‌بندی‌شده پرداخت‌ها با تمام جزئیات.", reply_markup=get_admin_reply_markup())

def show_stats_direct(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    t_u = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE submitted = 1")
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
        InlineKeyboardButton("📸 اینستاگرام", url=INSTAGRAM_URL)
    )
    markup.row(InlineKeyboardButton("🐦 توییتر (ایکس)", url=TWITTER_URL))
    
    markup.row(InlineKeyboardButton("🔗 دریافت لینک دعوت جذاب و اختصاصی", callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton("🎁 پاداش روزانه (100 PRS)", callback_data="daily_bonus"))
    markup.row(InlineKeyboardButton("🏆 برترین دعوت‌کنندگان (تاپ ۱۰)", callback_data="leaderboard"))
    markup.row(InlineKeyboardButton("📊 وضعیت من و رتبه", callback_data="my_status"), InlineKeyboardButton("📝 ارسال/ویرایش اطلاعات و ولت", callback_data="submit_info"))
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

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    
    # تبدیل اعداد فارسی به انگلیسی جهت سازگاری با کیبورد گوشی کاربران
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
        elif text == "📊 گزارش تفکیکی (فایل)":
            send_detailed_report_file(ADMIN_CHAT_ID)
            return
        elif text == "📈 آمار کلی ربات":
            show_stats_direct(ADMIN_CHAT_ID)
            return
        elif text == "🔙 خروج از حالت ادمین / منوی اصلی":
            bot.send_message(ADMIN_CHAT_ID, "مجدداً پنل مدیریتی ثابت فعال است.", reply_markup=get_admin_reply_markup())
            return
        elif text.startswith("/search "):
            query = text.replace("/search", "").strip()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, referred_by, ref_count, submitted, paid, verified, instagram_id, wallet, daily_count FROM users WHERE user_id = ? OR instagram_id LIKE ? OR wallet LIKE ?", 
                           (int(query) if query.isdigit() else 0, f"%{query}%", f"%{query}%"))
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                bot.send_message(ADMIN_CHAT_ID, "❌ هیچ کاربری با این مشخصات پیدا نشد.", reply_markup=get_admin_reply_markup())
                return
            res = "🔍 *نتیجه جستجوی ادمین:*\n\n"
            for r in rows:
                ref_cnt = r[2]
                d_cnt = r[8] if len(r) > 8 else 0
                total_tokens = calculate_total_tokens(ref_cnt, d_cnt)
                base_used, extra_count = get_ref_details(ref_cnt)
                res += f"👤 آیدی: `{r[0]}`\n👥 کل رفال: {ref_cnt} (ثابت: {base_used} | مازاد: {extra_count})\n🎁 توکن کل: {total_tokens:,} PRS\n📸 اینستا: `{r[6]}`\n👝 ولت: `{r[7]}`\n📌 ثبت فرم: `{r[3]}` | پرداخت: `{r[4]}`\n---\n"
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

    if text == "📊 وضعیت من و رتبه":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        wallet = user_data[6] if user_data and len(user_data) > 6 else "ثبت نشده"
        insta = user_data[7] if user_data and len(user_data) > 7 else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 مجموع توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"📸 اینستاگرام ثبت‌شده: `{insta}`\n"
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
    elif text == "📝 ارسال/ویرایش اطلاعات و ولت":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")
        if errors:
            bot.send_message(chat_id, "⚠️ **امکان ثبت اطلاعات وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.", parse_mode="Markdown")
            return
        bot.send_message(chat_id, "لطفاً اطلاعات خود را دقیقاً در ۲ خط بفرستید:\nخط ۱: آیدی اینستاگرام\nخط ۲: آدرس ولت (ارز دیجیتال)")
        return
    elif text == "📢 کانال تلگرام":
        bot.send_message(chat_id, f"📢 کانال رسمی: {CHANNEL_ID}")
        return
    elif text == "📸 اینستاگرام":
        bot.send_message(chat_id, f"📸 صفحه اینستاگرام: {INSTAGRAM_URL}")
        return
    elif text == "🐦 توییتر (ایکس)":
        bot.send_message(chat_id, f"🐦 صفحه توییتر: {TWITTER_URL}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ? AND submitted = 0", (user_id,))
    is_submitting = cursor.fetchone()
    conn.close()

    if is_submitting or text.startswith("و") or len(text.split('\n')) >= 2:
        parts = text.split('\n')
        if len(parts) >= 2:
            save_submission(user_id, parts[0], parts[1])
            bot.send_message(chat_id, "✅ اطلاعات و آدرس ولت شما با موفقیت ثبت/ویرایش شد.")
            show_main_menu(chat_id, user_id)
        else:
            bot.send_message(chat_id, "⚠️ فرمت اطلاعات ارسالی باید در ۲ خط باشد:\nخط اول: آیدی اینستاگرام\nخط دوم: آدرس ولت جدید")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if is_airdrop_finished() and user_id != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "🛑 ایردراپ به اتمام رسید.", show_alert=True)
        return

    if call.data.startswith("check_join_"):
        referrer_id = int(call.data.split("_")[2])
        
        if referrer_id == user_id:
            bot.answer_callback_query(call.id, "⚠️ شما نمی‌توانید از لینک خودتان استفاده کنید!", show_alert=True)
            return

        bot.answer_callback_query(call.id, "✅ تایید شد!")
        register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        
        show_main_menu(chat_id, user_id)
        return

    if call.data == "refresh_menu":
        bot.answer_callback_query(call.id, "🔄 پنل به‌روز شد.")
        show_main_menu(chat_id, user_id, message_id=call.message.message_id, edit=True)
        return

    if call.data == "get_ref_link":
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
    elif call.data == "leaderboard":
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
        
        text = "🏆 *۱۰ کاربر برتر ایردراپ (بیشترین توکن و دعوت)*:\n\n"
        for idx, (uid, r_cnt, total_t) in enumerate(top_10, 1):
            text += f"{idx}. آیدی: `{uid}` — 👥 دعوت: *{r_cnt}* — 🎁 توکن کل: *{total_t:,} PRS*\n"
        bot.send_message(chat_id, text, parse_mode="Markdown")
    elif call.data == "my_status":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0
        d_count = user_data[5] if user_data and len(user_data) > 5 else 0
        total_earned = calculate_total_tokens(ref_count, d_count)
        wallet = user_data[6] if user_data and len(user_data) > 6 else "ثبت نشده"
        insta = user_data[7] if user_data and len(user_data) > 7 else "ثبت نشده"
        user_rank = get_user_rank(user_id)
        
        status_msg = (
            f"📊 *اطلاعات حساب و وضعیت شما:*\n\n"
            f"👥 تعداد دعوت‌ها: `{ref_count} / {REQUIRED_REFERRALS}`\n"
            f"🎁 مجموع توکن کسب‌شده: `{total_earned:,} PRS`\n"
            f"🏅 رتبه شما در ایردراپ: `{user_rank}`\n"
            f"📸 اینستاگرام ثبت‌شده: `{insta}`\n"
            f"👝 آدرس ولت فعلی: `{wallet}`\n\n"
            f"💡 برای ویرایش آدرس ولت یا اینستاگرام خود، روی دکمه «ارسال/ویرایش اطلاعات و ولت» در منوی اصلی کلیک کنید."
        )
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, status_msg, parse_mode="Markdown")
    elif call.data == "submit_info":
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0

        errors = []
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")

        if errors:
            bot.answer_callback_query(call.id, "⚠️ شرایط لازم برای ثبت اطلاعات را ندارید!", show_alert=True)
            bot.send_message(
                chat_id,
                "⚠️ **امکان ثبت اطلاعات وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.",
                parse_mode="Markdown"
            )
            return

        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "لطفاً اطلاعات خود را دقیقاً در ۲ خط بفرستید (در صورت ارسال مجدد، آدرس ولت قبلی شما ویرایش/آپدیت می‌شود):\nخط ۱: آیدی اینستاگرام\nخط ۲: آدرس ولت (ارز دیجیتال)")

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
