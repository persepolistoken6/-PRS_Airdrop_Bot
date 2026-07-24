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
INSTAGRAM_URL = "Https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"
TWITTER_URL = "https://x.com/PersepolisPRS"
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
        actual_referrer = referrer_id if (referrer_id and referrer_id != user_id) else None
        cursor.execute("INSERT INTO users (user_id, referred_by, verified) VALUES (?, ?, 1)", (user_id, actual_referrer))
        
        if actual_referrer:
            cursor.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (actual_referrer,))
            conn.commit()
            try:
                cursor.execute("SELECT ref_count FROM users WHERE user_id = ?", (actual_referrer,))
                ref_row = cursor.fetchone()
                current_refs = ref_row[0] if ref_row else 1
                earned_now = calculate_tokens(current_refs)
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
        cursor.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    conn.close()

def save_submission(user_id, instagram_id, wallet):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET submitted = 1, instagram_id = ?, wallet = ?
        WHERE user_id = ?
    """, (instagram_id, wallet, user_id))
    conn.commit()
    conn.close()

def set_paid_status(user_id, status):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET paid = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

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
    
    # اگر کاربر از قبل ثبت‌نام کرده باشد
    user_data = get_user_data(user_id)
    if user_data and user_data[3] == 1:
        if referrer_id == user_id:
            bot.send_message(message.chat.id, "⚠️ شما نمی‌توانید از لینک دعوت خودتان استفاده کنید!")
            return
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
    markup.row(InlineKeyboardButton("👝 مدیریت و لیست ولت‌ها (تایید پرداخت)", callback_data="admin_wallets_list"))
    markup.row(InlineKeyboardButton("📊 آمار کلی ربات", callback_data="admin_stats"))
    markup.row(InlineKeyboardButton("📁 دریافت فایل خروجی کامل CSV", callback_data="admin_export"))
    
    help_text = (
        "👑 *پنل مدیریت ایردراپ*\n\n"
        "دستورات متنی ادمین:\n"
        "🔍 جستجو (آیدی، اینستا، ولت):\n`/search متن_یا_آیدی`\n\n"
        "❌ حذف کاربر:\n`/deleteuser آیدی_عددی`\n\n"
        "📢 ارسال همگانی به همه:\n`/sendall متن پیام`"
    )
    bot.send_message(message.chat.id, help_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return
    
    data = call.data
    if data == "admin_wallets_list":
        send_paginated_wallets(call.message, offset=0)
    elif data == "admin_stats":
        show_stats_direct(call.message)
    elif data == "admin_export":
        export_csv_direct(call.message)
    elif data.startswith("admin_pay_"):
        parts = data.split("_")
        target_id = int(parts[2])
        action = parts[3]
        new_val = 1 if action == "yes" else 0
        set_paid_status(target_id, new_val)
        
        bot.answer_callback_query(call.id, "✅ وضعیت پرداخت به‌روز شد.")
        try:
            update_wallet_message(call.message)
        except Exception:
            pass
    elif data.startswith("admin_page_"):
        offset = int(data.split("_")[2])
        send_paginated_wallets(call.message, offset=offset, edit=True)
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id)

def send_paginated_wallets(message, offset=0, edit=False):
    conn = sqlite3.connect('/tmp/referrals.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, ref_count, wallet, instagram_id, paid FROM users WHERE submitted = 1 ORDER BY ref_count DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        msg = "⚠️ هیچ کاربری هنوز فرم اطلاعاتش را ارسال نکرده است."
        if edit:
            bot.edit_message_text(msg, chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
        else:
            bot.send_message(ADMIN_CHAT_ID, msg)
        return

    limit = 5
    page_rows = rows[offset:offset+limit]

    text = f"👝 **لیست کاربران ثبت‌نام کرده (مجموع: {len(rows)} نفر):**\n\n"
    markup = InlineKeyboardMarkup()

    for uid, ref_cnt, wlt, insta, paid in page_rows:
        tokens = calculate_tokens(ref_cnt)
        status_str = "✅ پرداخت‌شده" if paid == 1 else "⏳ در انتظار پرداخت"
        
        text += f"📌 آیدی: `{uid}`\n" \
                f"👤 اینستا: `{insta}`\n" \
                f"👝 ولت: `{wlt}`\n" \
                f"🎁 مقدار: `{tokens} PRS` | وضعیت: *{status_str}*\n" \
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

def update_wallet_message(message):
    send_paginated_wallets(message, offset=0, edit=True)

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
    bot.send_message(ADMIN_CHAT_ID, f"📊 آمار کلی ربات:\n\n👤 کل کاربران استارت کرده: {t_u}\n📝 تعداد ثبت‌فرم‌ها: {t_s}\n💰 پرداخت‌شده‌ها: {t_p}", parse_mode="Markdown")

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
    file_bytes.name = 'users_backup.csv'
    bot.send_document(ADMIN_CHAT_ID, file_bytes, caption="📊 فایل پشتیبان کامل اطلاعات دیتابیس (CSV)")

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
    markup.row(InlineKeyboardButton("🔗 دریافت لینک دعوت جذاب و اختصاصی", callback_data="get_ref_link"))
    markup.row(InlineKeyboardButton("🏆 برترین دعوت‌کنندگان", callback_data="leaderboard"))
    markup.row(InlineKeyboardButton("📊 وضعیت من", callback_data="my_status"), InlineKeyboardButton("📝 ارسال اطلاعات و ولت", callback_data="submit_info"))
    
    caption_text = (
        f"🔴 *به ربات رسمی ایردراپ توکن هواداری پرسپولیس (PRS) خوش آمدید* 🏆\n\n"
        f"🪙 *معرفی پروژه:* توکن هواداری پرسپولیس بستری مدرن برای هواداران عزیز است تا در اکوسیستم دیجیتال باشگاه سهم داشته باشند.\n\n"
        f"🎁 *سیستم پاداش‌دهی و ایردراپ:*\n"
        f"▫️ پاداش پایه: `{BASE_REWARD} PRS` (پس از عضویت در کانال و دعوت `{REQUIRED_REFERRALS}` دوست)\n"
        f"▫️ پاداش به ازای هر دعوت مازاد: `{EXTRA_REWARD} PRS`\n\n"
        f"📊 *وضعیت شما در ربات:*\n"
        f"👥 دعوت‌های شما: `{ref_count} / {REQUIRED_REFERRALS}`\n"
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
            if not rows:
                bot.send_message(ADMIN_CHAT_ID, "❌ هیچ کاربری با این مشخصات پیدا نشد.")
                return
            res = "🔍 *نتیجه جستجوی ادمین:*\n\n"
            for r in rows:
                res += f"👤 آیدی: `{r[0]}`\n👥 رفال: `{r[2]}`\n📸 اینستا: `{r[6]}`\n👝 ولت: `{r[7]}`\n📌 ثبت فرم: `{r[3]}` | پرداخت: `{r[4]}`\n---\n"
            bot.send_message(ADMIN_CHAT_ID, res, parse_mode="Markdown")
            return
        elif text.startswith("/deleteuser "):
            target_id = text.replace("/deleteuser", "").strip()
            if target_id.isdigit():
                conn = sqlite3.connect('/tmp/referrals.db')
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE user_id = ?", (int(target_id),))
                cursor.execute("DELETE FROM captcha WHERE user_id = ?", (int(target_id),))
                conn.commit()
                conn.close()
                bot.send_message(ADMIN_CHAT_ID, f"✅ کاربر با آیدی عددی `{target_id}` به طور کامل از دیتابیس حذف شد.", parse_mode="Markdown")
            else:
                bot.send_message(ADMIN_CHAT_ID, "⚠️ آیدی عددی وارد شده معتبر نیست.")
            return
        elif text.startswith("/sendall "):
            broadcast_msg = text.replace("/sendall", "").strip()
            conn = sqlite3.connect('/tmp/referrals.db')
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
            bot.send_message(ADMIN_CHAT_ID, f"✅ ارسال همگانی با موفقیت به {success_count} کاربر انجام شد.")
            return

    # بررسی کپچا و جلوگیری قطعی از خودزنی
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
            
            # بررسی خودزنی پس از حل کپچا
            if referrer_id == user_id:
                bot.send_message(user_id, "⚠️ شما نمی‌توانید از لینک دعوت خودتان استفاده کنید!")
                return

            if check_channel(user_id):
                register_user_after_verify(user_id, referrer_id)
                show_main_menu(user_id, user_id)
            else:
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data=f"check_join_{referrer_id if referrer_id else 0}"))
                bot.send_message(
                    user_id,
                    f"❌ شما هنوز در کانال رسمی ما ({CHANNEL_ID}) عضو نشده‌اید!\n\n"
                    f"لطفاً ابتدا وارد کانال شوید و سپس روی دکمه زیر کلیک کنید:",
                    reply_markup=markup
                )
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
        if len(parts) >= 2:
            save_submission(user_id, parts[0], parts[1])
            bot.send_message(user_id, "✅ اطلاعات با موفقیت ثبت شد.")
            show_main_menu(user_id, user_id)
        else:
            bot.send_message(user_id, "⚠️ فرمت اطلاعات ارسالی باید در ۲ خط باشد:\nخط اول: آیدی اینستاگرام\nخط دوم: آدرس ولت")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    if call.data.startswith("check_join_"):
        referrer_id = int(call.data.split("_")[2])
        
        if referrer_id == user_id:
            bot.answer_callback_query(call.id, "⚠️ شما نمی‌توانید از لینک خودتان استفاده کنید!", show_alert=True)
            return

        if check_channel(user_id):
            bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد!")
            register_user_after_verify(user_id, referrer_id if referrer_id != 0 else None)
            try:
                bot.delete_message(user_id, call.message.message_id)
            except Exception:
                pass
            show_main_menu(user_id, user_id)
        else:
            bot.answer_callback_query(call.id, "❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)
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
            bot.send_photo(
                chat_id=user_id,
                photo=BANNER_FILE_ID,
                caption=link_text
            )
        except Exception:
            bot.send_message(
                chat_id=user_id,
                text=link_text
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
        bot.answer_callback_query(call.id, f"📊 دعوت‌ها: {ref_count}/{REQUIRED_REFERRALS} | توکن: {earned} PRS", show_alert=True)
    elif call.data == "submit_info":
        is_member = check_channel(user_id)
        user_data = get_user_data(user_id)
        ref_count = user_data[0] if user_data else 0

        errors = []
        if not is_member:
            errors.append(f"❌ شما هنوز در کانال رسمی ربات ({CHANNEL_ID}) عضو نشده‌اید.")
        if ref_count < REQUIRED_REFERRALS:
            errors.append(f"❌ تعداد دعوت‌های شما ({ref_count} نفر) به حد نصاب نرسیده است. (حداقل مورد نیاز: {REQUIRED_REFERRALS} نفر)")

        if errors:
            bot.answer_callback_query(call.id, "⚠️ شرایط لازم برای ثبت اطلاعات را ندارید!", show_alert=True)
            bot.send_message(
                user_id,
                "⚠️ **امکان ثبت اطلاعات وجود ندارد:**\n\n" + "\n".join(errors) + "\n\nلطفاً پس از رفع موانع دوباره تلاش کنید.",
                parse_mode="Markdown"
            )
            return

        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "لطفاً اطلاعات خود را دقیقاً در ۲ خط بفرستید:\nخط ۱: آیدی اینستاگرام\nخط ۲: آدرس ولت (ارز دیجیتال)")

if __name__ == "__main__":
    print("Bot is starting with Long Polling...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
