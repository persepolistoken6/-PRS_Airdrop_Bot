import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from collections import defaultdict
import random
import io
import re

# ⚙️ اطلاعات اختصاصی پروژه:
TOKEN = "8629221284:AAFDhLrtfonZCERsH4lcOoDVwF-exomOxGs"
BOT_USERNAME = "PRS_Airdrop_Bot"
CHANNEL_ID = "@persepolisToken6"
TWITTER_LINK = "https://x.com/PersepolisPRS"
INSTAGRAM_LINK = "https://www.instagram.com/persepolistoken6?igsh=eHBwbzdtd2ZoaWI5"
ADMIN_CHAT_ID = 6661478622
REQUIRED_REFERRALS = 5  # حداقل دعوت لازم

# ⚙️ تنظیمات توکنومیکس ایردراپ:
BASE_REWARD = 1000      # توکن پایه برای ۵ دعوت اول
EXTRA_REWARD = 200      # توکن اضافی به ازای هر ۱ دعوت بیشتر از ۵ نفر

# 🖼 فایل آیدی بنر تصویری پرسپولیس
BANNER_FILE_ID = "AgACAgQAAxkBAAMfamINNXWkFr-wKlONFWAEHF2z-vgAAsgNaxtnhwABU-cbUHZe_7c6AQADAgADeQADPQQ"

bot = telebot.TeleBot(TOKEN)

# 💾 آماده‌سازی دیتابیس
def init_db():
    conn = sqlite3.connect('referrals.db')
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
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT ref_count, submitted, paid, verified FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_user_after_verify(user_id, referrer_id):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO users (user_id, referred_by, verified) VALUES (?, ?, 1)', (user_id, referrer_id))
        if referrer_id and referrer_id != user_id:
            cursor.execute('UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()
    else:
        cursor.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
    conn.close()

def save_submission(user_id, info_text, instagram_id, wallet):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET submitted = 1, user_info = ?, instagram_id = ?, wallet = ?
        WHERE user_id = ?
    ''', (info_text, instagram_id, wallet, user_id))
    conn.commit()
    conn.close()

def toggle_paid_status(user_id):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT paid FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        new_status = 0 if row[0] == 1 else 1
        cursor.execute('UPDATE users SET paid = ? WHERE user_id = ?', (new_status, user_id))
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

    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('REPLACE INTO captcha (user_id, answer, pending_referrer) VALUES (?, ?, ?)', (user_id, correct_ans, referrer_id))
    conn.commit()
    conn.close()

    bot.send_message(
        message.chat.id,
        f"🤖 **تایید هویت امنیتی (ضد ربات و فیک):**\n\n"
        f"لطفاً حاصل جمع زیر را به عنوان پاسخ ارسال کنید:\n\n"
        f"❓ **{num1} + {num2} = ؟**\n\n"
        f"*(عدد پاسخ را در چت ارسال کنید)*",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📋 لیست کاربران و تایید پرداخت‌ها", callback_data="admin_users"))
    markup.add(InlineKeyboardButton("📦 لیست یکجای ولت‌ها", callback_data="admin_wallets"))
    markup.add(InlineKeyboardButton("📊 دسته‌بندی مقادیر توکن یکسان", callback_data="admin_batch"))
    markup.add(InlineKeyboardButton("📈 آمار کلی ربات", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("📁 دریافت فایل خروجی CSV (اکسل)", callback_data="admin_export"))
    markup.add(InlineKeyboardButton("🔍 راهنمای جستجوی کاربر", callback_data="admin_search_info"))
    markup.add(InlineKeyboardButton("📢 راهنمای ارسال پیام همگانی", callback_data="admin_broadcast_info"))

    bot.reply_to(message, "👑 **به پنل مدیریت حرفه‌ای ربات ایردراپ خوش آمدید:**\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", reply_markup=markup, parse_mode='Markdown')

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
    elif call.data == "admin_export":
        export_csv_direct(call.message)
    elif call.data == "admin_search_info":
        bot.send_message(ADMIN_CHAT_ID, "🔍 **نحوه جستجوی کاربر:**\n\nدستور زیر را به همراه آیدی عددی، آیدی اینستاگرام یا ولت بفرستید:\n\n`/search 176915374` یا `/search my_insta`", parse_mode='Markdown')
    elif call.data == "admin_broadcast_info":
        bot.send_message(ADMIN_CHAT_ID, "📢 **نحوه ارسال پیام همگانی:**\n\nدستور زیر را بنویسید:\n\n`/sendall متن پیام شما`", parse_mode='Markdown')

    bot.answer_callback_query(call.id)

def show_eligible_users_direct(message):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, ref_count, paid, user_info, instagram_id, wallet FROM users WHERE submitted = 1 ORDER BY paid ASC, ref_count DESC')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "📂 هنوز هیچ کاربری فرم اطلاعاتش را نفرستاده است.")
        return

    bot.send_message(ADMIN_CHAT_ID, "📋 **لیست کاربران واجد شرایط دریافت توکن:**")
    for uid, ref_cnt, paid_status, info, insta, wlt in rows:
        earned_tokens = calculate_tokens(ref_cnt)
        status_text = "✅ **پرداخت شده**" if paid_status == 1 else "⏳ **در انتظار پرداخت**"

        text = (
            f"👤 **آیدی عددی:** `{uid}`\n"
            f"📸 **اینستاگرام:** `{insta if insta else 'ثبت نشده'}`\n"
            f"📦 **ولت:** `{wlt if wlt else 'ثبت نشده'}`\n"
            f"👥 **تعداد دعوت:** {ref_cnt} نفر\n"
            f"💰 **سهمیه توکن:** {earned_tokens} PRS\n"
            f"📊 **وضعیت:** {status_text}\n"
            f"📝 **متن کامل ارسالی:**\n{info}"
        )
        markup = InlineKeyboardMarkup()
        btn_text = "❌ لغو پرداخت" if paid_status == 1 else "✅ تایید پرداخت"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"pay_{uid}"))
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode='Markdown')

def get_all_wallets_direct(message):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, ref_count, wallet, instagram_id FROM users WHERE submitted = 1 AND paid = 0 ORDER BY ref_count DESC')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "🎉 هیچ کاربر در انتظار پرداختی وجود ندارد!")
        return

    text = "📦 **لیست ولت‌ها و مقادیر برای پرداخت:**\n\n"
    for uid, ref_cnt, wlt, insta in rows:
        tokens = calculate_tokens(ref_cnt)
        text += f"آیدی: `{uid}` | اینستا: `{insta}`\nولت: `{wlt}` | مقدار: `{tokens}` PRS\n-------------------\n"

    bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown')

def batch_by_tokens_direct(message):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, ref_count, wallet, instagram_id FROM users WHERE submitted = 1 AND paid = 0')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "🎉 هیچ کاربر در انتظار پرداختی وجود ندارد!")
        return

    grouped = defaultdict(list)
    for uid, ref_cnt, wlt, insta in rows:
        tokens = calculate_tokens(ref_cnt)
        grouped[tokens].append((uid, wlt, insta))

    text = "📊 **دسته‌بندی کاربران بر اساس مقدار توکن یکسان:**\n\n"
    for tokens, users_list in sorted(grouped.items(), reverse=True):
        text += f"🎁 **مقدار سهمیه برای هر نفر: `{tokens}` توکن**\n"
        text += f"👥 تعداد افراد: {len(users_list)} نفر\n\n"
        for uid, wlt, insta in users_list:
            text += f"• آیدی: `{uid}` | اینستا: `{insta}`\n  ولت: `{wlt}`\n"
        text += "-------------------\n"

    bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown')

def show_stats_direct(message):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE submitted = 1')
    submitted_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE paid = 1')
    paid_users = cursor.fetchone()[0]

    cursor.execute('SELECT ref_count FROM users WHERE submitted = 1 AND paid = 0')
    rows = cursor.fetchall()
    conn.close()

    pending_tokens = sum([calculate_tokens(r[0]) for r in rows])

    text = (
        "📈 **آمار کلی ربات ایردراپ:**\n\n"
        f"👥 **کل کاربران تایید شده:** {total_users} نفر\n"
        f"📝 **تعداد فرم‌های ارسال‌شده:** {submitted_users} نفر\n"
        f"✅ **تعداد پرداخت‌های موفق:** {paid_users} نفر\n"
        f"⏳ **مجموع توکن‌های در انتظار واریز:** {pending_tokens} PRS"
    )
    bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown')

def export_csv_direct(message):
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, ref_count, paid, instagram_id, wallet, user_info FROM users WHERE submitted = 1')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(ADMIN_CHAT_ID, "📂 هیچ داده‌ای برای خروجی وجود ندارد.")
        return

    output = io.StringIO()
    output.write("User_ID,Referrals,Tokens,Paid_Status,Instagram,Wallet,Info\n")
    for uid, ref_cnt, paid_status, insta, wlt, info in rows:
        tokens = calculate_tokens(ref_cnt)
        clean_insta = f'"{insta}"' if insta else '""'
        clean_wlt = f'"{wlt}"' if wlt else '""'
        clean_info = f'"{info.replace(chr(10), " | ")}"' if info else '""'
        output.write(f"{uid},{ref_cnt},{tokens},{paid_status},{clean_insta},{clean_wlt},{clean_info}\n")

    bio = io.BytesIO()
    bio.write(output.getvalue().encode('utf-8-sig'))
    bio.seek(0)
    bio.name = "airdrop_users.csv"

    bot.send_document(ADMIN_CHAT_ID, bio, caption="📁 **فایل خروجی اطلاعات کاربران ایردراپ (فرمت CSV)**", parse_mode='Markdown')

@bot.message_handler(commands=['sendall'])
def send_all_message(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    text = message.text.replace('/sendall', '').strip()
    if not text:
        bot.reply_to(message, "⚠️ لطفاً متن پیام را بعد از دستور بفرستید.\nمثال:\n`/sendall سلام به همه کاربران`", parse_mode='Markdown')
        return

    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE verified = 1')
    users = cursor.fetchall()
    conn.close()

    success, failed = 0, 0
    bot.send_message(ADMIN_CHAT_ID, f"⏳ در حال ارسال پیام به {len(users)} کاربر...")

    for user in users:
        try:
            bot.send_message(user[0], text)
            success += 1
        except Exception:
            failed += 1

    bot.send_message(ADMIN_CHAT_ID, f"📢 **نتیجه ارسال پیام همگانی:**\n\n✅ تحویل داده شد: {success} نفر\n❌ ناموفق: {failed} نفر")

@bot.message_handler(commands=['search'])
def search_user(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ لطفاً آیدی عددی، آیدی اینستاگرام یا ولت را بنویسید.\nمثال:\n`/search 176915374`", parse_mode='Markdown')
        return

    query_str = args[1].strip()
    query = f"%{query_str}%"

    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    # جستجو بر اساس آیدی کاربر، آیدی اینستاگرام یا ولت
    cursor.execute('''
        SELECT user_id, ref_count, submitted, paid, user_info, instagram_id, wallet
        FROM users
        WHERE CAST(user_id AS TEXT) LIKE ? OR instagram_id LIKE ? OR wallet LIKE ? OR user_info LIKE ?
    ''', (query, query, query, query))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.reply_to(message, "❌ هیچ کاربری با این مشخصات یافت نشد.")
        return

    for uid, ref_cnt, submitted, paid_status, info, insta, wlt in rows:
        earned_tokens = calculate_tokens(ref_cnt)
        status_text = "✅ **پرداخت شده**" if paid_status == 1 else "⏳ **در انتظار پرداخت**"
        sub_status = "بله" if submitted == 1 else "خیر"

        # استخراج لیست زیرمجموعه‌ها
        conn = sqlite3.connect('referrals.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM users WHERE referred_by = ?', (uid,))
        sub_users = [str(r[0]) for r in c.fetchall()]
        conn.close()

        subs_text = ", ".join(sub_users) if sub_users else "هنوز کسی را دعوت نکرده"

        text = (
            f"🔍 **نتیجه جستجو:**\n\n"
            f"👤 **آیدی عددی:** `{uid}`\n"
            f"📸 **آیدی اینستاگرام:** `{insta if insta else 'ثبت نشده'}`\n"
            f"📦 **آدرس ولت:** `{wlt if wlt else 'ثبت نشده'}`\n"
            f"👥 **تعداد دعوت:** {ref_cnt} نفر\n"
            f"📋 **لیست آیدی‌های دعوت‌شده:**\n`{subs_text}`\n\n"
            f"💰 **سهمیه توکن:** {earned_tokens} PRS\n"
            f"📋 **ارسال فرم:** {sub_status}\n"
            f"📊 **وضعیت:** {status_text}\n"
            f"📝 **متن کامل اطلاعات:**\n{info if info else 'ثبت نشده'}"
        )

        markup = InlineKeyboardMarkup()
        if submitted == 1:
            btn_text = "❌ لغو پرداخت" if paid_status == 1 else "✅ تایید پرداخت"
            markup.add(InlineKeyboardButton(btn_text, callback_data=f"pay_{uid}"))

        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['users'])
def show_eligible_users(message):
    if message.from_user.id != ADMIN_CHAT_ID: return
    show_eligible_users_direct(message)

@bot.message_handler(commands=['wallets'])
def get_all_wallets(message):
    if message.from_user.id != ADMIN_CHAT_ID: return
    get_all_wallets_direct(message)

@bot.message_handler(commands=['batch'])
def batch_by_tokens(message):
    if message.from_user.id != ADMIN_CHAT_ID: return
    batch_by_tokens_direct(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def handle_payment_toggle(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return

    target_user_id = int(call.data.split('_')[1])
    new_status = toggle_paid_status(target_user_id)

    if new_status is not None:
        status_str = "✅ پرداخت شده" if new_status == 1 else "⏳ در انتظار پرداخت"
        bot.answer_callback_query(call.id, f"وضعیت به: {status_str} تغییر کرد.")

        try:
            conn = sqlite3.connect('referrals.db')
            cursor = conn.cursor()
            cursor.execute('SELECT ref_count, paid, user_info, instagram_id, wallet FROM users WHERE user_id = ?', (target_user_id,))
            r = cursor.fetchone()
            conn.close()

            if r:
                ref_cnt, paid_status, info, insta, wlt = r
                earned_tokens = calculate_tokens(ref_cnt)
                status_text = "✅ **پرداخت شده**" if paid_status == 1 else "⏳ **در انتظار پرداخت**"

                updated_text = (
                    f"👤 **آیدی عددی:** `{target_user_id}`\n"
                    f"📸 **اینستاگرام:** `{insta if insta else 'ثبت نشده'}`\n"
                    f"📦 **ولت:** `{wlt if wlt else 'ثبت نشده'}`\n"
                    f"👥 **تعداد دعوت:** {ref_cnt} نفر\n"
                    f"💰 **سهمیه توکن:** {earned_tokens} PRS\n"
                    f"📊 **وضعیت:** {status_text}\n"
                    f"📝 **اطلاعات ارسالی کاربر:**\n{info}"
                )

                markup = InlineKeyboardMarkup()
                btn_text = "❌ لغو پرداخت" if paid_status == 1 else "✅ تایید پرداخت"
                markup.add(InlineKeyboardButton(btn_text, callback_data=f"pay_{target_user_id}"))

                bot.edit_message_text(updated_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            print(e)

def show_main_menu(chat_id, user_id):
    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    earned_tokens = calculate_tokens(ref_count)

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("۱. عضویت در کانال تلگرام 📢", url=f"https://t.me/{CHANNEL_ID[1:]}"))
    markup.add(InlineKeyboardButton("۲. فالو کردن اینستاگرام 📸", url=INSTAGRAM_LINK))
    markup.add(InlineKeyboardButton("۳. دنبال کردن توییتر (X) 🐦", url=TWITTER_LINK))
    markup.add(InlineKeyboardButton("🖼 دریافت بنر تصویری و لینک اختصاصی", callback_data='get_banner'))
    markup.add(InlineKeyboardButton("📊 وضعیت دعوت‌ها و پاداش", callback_data='check_status'))
    markup.add(InlineKeyboardButton("ثبت اطلاعات و دریافت توکن 🔄", callback_data='check_sub'))

    text = (
        "👋 به ایردراپ Persepolis Fan Token (PRS) خوش آمدید!\n\n"
        "جهت دریافت توکن‌های رایگان، مراحل زیر را انجام دهید:\n"
        "۱. عضو کانال تلگرام شوید.\n"
        "۲. پیج اینستاگرام ما را فالو کنید.\n"
        "۳. صفحه توییتر ما را دنبال کنید.\n"
        f"۴. حداقل {REQUIRED_REFERRALS} نفر را با لینک اختصاصی خود دعوت کنید.\n\n"
        f"🎁 پاداش اولیه (۵ دعوت): {BASE_REWARD} توکن PRS\n"
        f"➕ پاداش هر دعوت اضافه: {EXTRA_REWARD} توکن PRS بیشتر!\n\n"
        f"👥 تعداد دعوت‌های شما: {ref_count} نفر\n"
        f"💰 توکن‌های کسب‌شده شما: {earned_tokens} PRS\n\n"
        "👇 برای دریافت **لینک اختصاصی** و **بنر تصویری توکن**، روی دکمه زیر بزنید:"
    )
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ['check_sub', 'check_status', 'get_banner'])
def callback_handler(call):
    user_id = call.from_user.id
    user_data = get_user_data(user_id)
    ref_count = user_data[0] if user_data else 0
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    earned_tokens = calculate_tokens(ref_count)

    if call.data == 'get_banner':
        banner_caption = (
            "🔥 **ایردراپ بزرگ Persepolis Fan Token (PRS) شروع شد!**\n\n"
            "🏆 توکن هواداری پرسپولیس روی شبکه بایننس اسمارت چین (BEP-20)\n"
            "🎁 **۱,۰۰۰ توکن رایگان** پاداش دعوت از ۵ دوست!\n"
            "⚡️ +۲۰۰ توکن اضافه به ازای هر دعوت بیشتر\n\n"
            "🔗 **لینک دعوت اختصاصی شما:**\n"
            f"{ref_link}\n\n"
            "همین حالا این بنر را همراه با لینک خود برای دوستانتان بفرستید تا توکن بگیرید!"
        )

        try:
            bot.send_photo(call.message.chat.id, BANNER_FILE_ID, caption=banner_caption, parse_mode='Markdown')
        except Exception:
            bot.send_message(call.message.chat.id, banner_caption, parse_mode='Markdown')

        bot.answer_callback_query(call.id)
        return

    if call.data == 'check_status':
        bot.answer_callback_query(call.id, f"📊 تعداد دعوت‌های شما: {ref_count} نفر\n💰 توکن‌های کسب‌شده: {earned_tokens} PRS", show_alert=True)
        return

    if call.data == 'check_sub':
        if not check_channel(user_id):
            bot.answer_callback_query(call.id, "❌ هنوز در کانال تلگرام عضو نشده‌اید!", show_alert=True)
            return

        if ref_count < REQUIRED_REFERRALS:
            bot.answer_callback_query(
                call.id,
                f"❌ شما فقط {ref_count} نفر را دعوت کرده‌اید! برای ثبت‌نام باید حداقل {REQUIRED_REFERRALS} نفر را دعوت کنید.",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id, "✅ تمام مراحل تایید شد!")
        send_success(call.message.chat.id, earned_tokens)

def send_success(chat_id, earned_tokens):
    text = (
        f"🎉 تبریک! شما واجد شرایط دریافت {earned_tokens} توکن PRS هستید.\n\n"
        "لطفاً اطلاعات زیر را در قالب یک پیام ارسال کنید:\n"
        "۱. آیدی اینستاگرام\n"
        "۲. آدرس ولت (BEP-20)\n\n"
        "مثال:\n"
        "Insta: @my_instagram\n"
        "Wallet: 0x123456789..."
    )
    bot.send_message(chat_id, text)

@bot.message_handler(content_types=['text'])
def handle_text_messages(message):
    if message.text.startswith('/'):
        return

    user_id = message.from_user.id

    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('SELECT answer, pending_referrer FROM captcha WHERE user_id = ?', (user_id,))
    captcha_row = cursor.fetchone()

    if captcha_row:
        correct_ans, referrer_id = captcha_row
        if message.text.strip().isdigit() and int(message.text.strip()) == correct_ans:
            cursor.execute('DELETE FROM captcha WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()

            register_user_after_verify(user_id, referrer_id)
            bot.reply_to(message, "✅ تایید هویت با موفقیت انجام شد!")
            show_main_menu(message.chat.id, user_id)
            return
        else:
            conn.close()
            bot.reply_to(message, "❌ پاسخ اشتباه است! لطفاً دوباره حاصل جمع خواسته شده را با دقت بفرستید.")
            return

    conn.close()

    user_data = get_user_data(user_id)
    if not user_data or user_data[3] == 0:
        bot.reply_to(message, "⚠️ لطفاً ابتدا ربات را با دستور `/start` شروع کرده و تایید هویت را انجام دهید.", parse_mode='Markdown')
        return

    if user_data[0] < REQUIRED_REFERRALS:
        bot.reply_to(message, f"⚠️ لطفاً ابتدا شبکه‌های اجتماعی را دنبال کرده و حداقل {REQUIRED_REFERRALS} نفر را دعوت کنید، سپس دکمه ثبت اطلاعات را بزنید.")
        return

    user = message.from_user
    ref_count = user_data[0]
    earned_tokens = calculate_tokens(ref_count)
    username_text = f"@{user.username}" if user.username else "بدون آیدی"

    # استخراج هوشمند آیدی اینستاگرام و ولت از متن ارسالی کاربر
    text_content = message.text
    instagram_id = "ثبت نشده"
    wallet = "ثبت نشده"

    # جستجوی ولت (با شروع 0x)
    wallet_match = re.search(r'(0x[a-fA-F0-9]{40})', text_content)
    if wallet_match:
        wallet = wallet_match.group(1)

    # جستجوی اینستاگرام (کلمات بعد از Insta یا آیدی‌های شروع شده با @)
    insta_match = re.search(r'(?:insta|instagram|اینستا|اینستاگرام)[:\-]?\s*(@?[\w\.]+)', text_content, re.IGNORECASE)
    if insta_match:
        instagram_id = insta_match.group(1)
    else:
        # اگر کلیدواژه نداشت، اولین کلمه شبیه به آیدی یا @ را به عنوان اینستاگرام در نظر بگیر
        words = text_content.split()
        for w in words:
            if w.startswith('@') and w != username_text:
                instagram_id = w
                break

    full_info = f"یوزرنیم تلگرام: {username_text}\nمتن کاربر:\n{message.text}"
    save_submission(user_id, full_info, instagram_id, wallet)

    admin_text = (
        f"📥 درخواست ایردراپ جدید (PRS):\n\n"
        f"یوزرنیم تلگرام: {username_text}\n"
        f"آیدی عددی: {user.id}\n"
        f"📸 اینستاگرام: {instagram_id}\n"
        f"📦 ولت: {wallet}\n"
        f"تعداد دعوت‌ها: {ref_count} نفر\n"
        f"سهمیه توکن: {earned_tokens} PRS\n\n"
        f"متن کامل اطلاعات ارسالی:\n{message.text}"
    )
    bot.send_message(ADMIN_CHAT_ID, admin_text)
    bot.reply_to(message, f"🙏 اطلاعات شما ثبت شد! تعداد {earned_tokens} توکن PRS در زمان توزیع به ولت شما واریز خواهد شد.")

bot.infinity_polling()
